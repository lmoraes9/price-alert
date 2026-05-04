"""
Monitor de Brinco Roubado — Palavras-chave + Busca Reversa Yandex
==================================================================
Drop-in replacement. Usa os MESMOS secrets que você já tem:
  - TELEGRAM_TOKEN
  - TELEGRAM_CHAT_ID

O QUE FAZ:
  1. Busca palavras-chave em OLX, Mercado Livre e Enjoei (rápido, confiável)
  2. Faz busca REVERSA POR IMAGEM no Yandex (best effort) e FILTRA pra
     mostrar só resultados em marketplaces brasileiros
  3. Manda alerta no Telegram de cada novo achado
  4. Mantém histórico em SQLite (não te avisa duas vezes)

PRÉ-REQUISITO:
  Suba o arquivo `brinco.jpg` na raiz do repositório (mesmo lugar do .py).
  Na primeira execução, o script faz upload anônimo pro Imgur (1x só) e
  salva a URL pública num arquivo `imgur_url.txt`. As próximas execuções
  reutilizam a mesma URL.

LIMITAÇÕES HONESTAS:
  - Yandex pode bloquear o IP do GitHub Actions a qualquer momento.
    Se bloquear, o resto do script (palavras-chave) continua funcionando.
  - O algoritmo do Yandex acha similares, não idênticos. O filtro de
    marketplace BR remove a maior parte do ruído.
"""

import os
import sqlite3
import time
import random
import re
import base64
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIGURAÇÃO — você edita ESTA seção
# ============================================================

# Palavras-chave melhoradas: cobertura ampla, sinônimos e marcas conhecidas
# que fazem brincos de flor com diamantes em pavê (formato 4 pétalas marquise)
QUERIES = [
    # Descrições genéricas
    "brinco flor diamante ouro branco",
    "brinco flor brilhante ouro branco",
    "brinco diamante 4 petalas",
    "brinco diamante quatro petalas",
    "brinco navete diamante ouro branco",
    "brinco cluster diamante ouro branco",
    "brinco estrela diamante ouro branco",
    "brinco floral diamante ouro 18k",
    "brinco pave diamante flor",
    "brinco chuveiro diamante ouro branco",
    # Marcas brasileiras que fazem esse modelo
    "brinco vivara flor diamante",
    "brinco hstern flor diamante",
    "brinco h.stern petali",
    "brinco roberto coin princess flower",
    "brinco pasquale bruni petit garden",
    # Internacional comum em e-commerce BR
    "brinco louis vuitton star blossom",
    "brinco tiffany flor diamante",
]

# Filtros: precisa ter pelo menos UMA destas no título
PALAVRAS_OBRIGATORIAS = ["diamante", "brilhante", "ouro branco", "flor",
                         "petala", "pétala", "floral", "navete",
                         "estrela", "blossom", "petali", "petit garden"]

# Ignora bijuteria óbvia
PALAVRAS_EXCLUIR = ["zirconia", "zircônia", "folheado", "banhado",
                    "bijuteria", "infantil", "criança", "imitação",
                    "fantasia", "prata 925", "prata fina", "aço inox",
                    "aço cirúrgico", "aço cirurgico"]

# URL pública da foto do brinco (já hospedada no Imgur)
FOTO_URL_PUBLICA = "https://i.imgur.com/QeO0dJ5.jpeg"

# Cidades prioritárias (anúncio aqui = mais suspeito, alerta destacado)
CIDADES_PRIORITARIAS = ["sao paulo", "são paulo", "sp", "guarulhos",
                        "osasco", "santo andre", "santo andré", "abc"]

# DOMÍNIOS de marketplace BR que o filtro do Yandex vai aceitar
MARKETPLACES_BR = [
    "olx.com.br",
    "mercadolivre.com.br",
    "produto.mercadolivre.com.br",
    "lista.mercadolivre.com.br",
    "enjoei.com.br",
    "etiquetaunica.com.br",
    "abrechofeminino.com.br",
    "repassa.com.br",
    "facebook.com",          # marketplace
    "instagram.com",          # vendedoras de joia usada
    "shopee.com.br",
    "amazon.com.br",
    "magazineluiza.com.br",
    "americanas.com.br",
    "submarino.com.br",
    "shoptime.com.br",
    "leiloesjudiciais.com.br",
    "leilaovip.com.br",
    "superbid.net",
    "sodresantoro.com.br",
    "milanleiloeiro.com.br",
]

# ============================================================
# CREDENCIAIS — vêm dos secrets que você JÁ tem configurados
# ============================================================

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_DIR = Path(__file__).parent
DB       = BASE_DIR / "anuncios_vistos.db"
FOTO     = BASE_DIR / "brinco.jpg"
URL_CACHE = BASE_DIR / "imgur_url.txt"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# ============================================================
# TELEGRAM (mesmo do seu script antigo, suporta múltiplos IDs)
# ============================================================

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ Telegram não configurado. Mensagem seria:\n{message}")
        return
    for chat_id in TELEGRAM_CHAT_ID.split(","):
        cid = chat_id.strip()
        if not cid:
            continue
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": message,
                      "disable_web_page_preview": False},
                timeout=10,
            )
            print(f"  ✅ Telegram -> {cid}")
        except Exception as e:
            print(f"  ⚠️ Erro Telegram: {e}")

# ============================================================
# BANCO
# ============================================================

def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vistos (
            url TEXT PRIMARY KEY,
            site TEXT, titulo TEXT, preco TEXT,
            local TEXT, fonte TEXT, visto_em TEXT
        )
    """)
    conn.commit()
    return conn

def ja_visto(conn, url):
    return conn.execute("SELECT 1 FROM vistos WHERE url = ?", (url,)).fetchone() is not None

def marcar_visto(conn, a):
    conn.execute(
        "INSERT OR IGNORE INTO vistos VALUES (?, ?, ?, ?, ?, ?, ?)",
        (a["url"], a["site"], a["titulo"], a.get("preco", ""),
         a.get("local", ""), a.get("fonte", "palavra-chave"),
         datetime.now().isoformat())
    )
    conn.commit()

# ============================================================
# FILTROS
# ============================================================

def passa_filtros(titulo):
    t = titulo.lower()
    if any(p in t for p in PALAVRAS_EXCLUIR):
        return False
    if not any(p in t for p in PALAVRAS_OBRIGATORIAS):
        return False
    return True

def eh_prioritario(local):
    if not local:
        return False
    return any(c in local.lower() for c in CIDADES_PRIORITARIAS)

def eh_marketplace_br(url):
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return False
    return any(host == mp or host.endswith("." + mp) or mp in host
               for mp in MARKETPLACES_BR)

# ============================================================
# SCRAPERS DE PALAVRA-CHAVE
# ============================================================

def scrape_olx(query):
    url = f"https://www.olx.com.br/estado-sp?q={quote_plus(query)}"
    out = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return out
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select('a[data-ds-component="DS-AdCard"]'):
            link = card.get("href", "")
            titulo = card.select_one('h2')
            preco = card.select_one('[data-ds-component="DS-Text"]')
            local = card.find(string=re.compile(r"[A-Z][a-zà-ú]+,\s*[A-Z]{2}"))
            if not link or not titulo:
                continue
            out.append({
                "site": "OLX", "url": link,
                "titulo": titulo.get_text(strip=True),
                "preco": preco.get_text(strip=True) if preco else "",
                "local": local.strip() if local else "",
                "fonte": "palavra-chave",
            })
    except Exception as e:
        print(f"    ⚠️ OLX erro: {e}")
    return out

def scrape_mercado_livre(query):
    url = f"https://lista.mercadolivre.com.br/{quote_plus(query)}"
    out = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return out
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select('li.ui-search-layout__item'):
            link_el = card.select_one('a.poly-component__title, a.ui-search-link')
            if not link_el:
                continue
            link = link_el.get("href", "").split("#")[0]
            preco_el = card.select_one('.poly-price__current, .andes-money-amount')
            local_el = card.select_one('.poly-component__location, .ui-search-item__location')
            out.append({
                "site": "Mercado Livre", "url": link,
                "titulo": link_el.get_text(strip=True),
                "preco": preco_el.get_text(strip=True) if preco_el else "",
                "local": local_el.get_text(strip=True) if local_el else "",
                "fonte": "palavra-chave",
            })
    except Exception as e:
        print(f"    ⚠️ ML erro: {e}")
    return out

def scrape_enjoei(query):
    url = f"https://www.enjoei.com.br/busca?q={quote_plus(query)}"
    out = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return out
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select('a[href*="/p/"]')[:20]:
            href = card.get("href", "")
            link = href if href.startswith("http") else f"https://www.enjoei.com.br{href}"
            titulo = card.get("title") or card.get_text(strip=True)[:120]
            if not titulo:
                continue
            out.append({
                "site": "Enjoei", "url": link, "titulo": titulo,
                "preco": "", "local": "", "fonte": "palavra-chave",
            })
    except Exception as e:
        print(f"    ⚠️ Enjoei erro: {e}")
    return out

# ============================================================
# BUSCA REVERSA YANDEX
# ============================================================

def upload_para_imgur(foto_path):
    """
    Upload anônimo da foto pro Imgur. Funciona sem API key (rate limit baixo
    mas suficiente — só rodamos 1x). Retorna a URL pública da imagem.
    """
    print("  📤 Fazendo upload da foto pro Imgur (1ª vez só)...")
    try:
        with open(foto_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        # Client-ID público do Imgur (qualquer um funciona pra upload anônimo)
        r = requests.post(
            "https://api.imgur.com/3/image",
            headers={"Authorization": "Client-ID 546c25a59c58ad7"},
            data={"image": img_b64, "type": "base64"},
            timeout=30,
        )
        if r.status_code == 200:
            url = r.json()["data"]["link"]
            URL_CACHE.write_text(url)
            print(f"  ✅ Foto hospedada: {url}")
            return url
        else:
            print(f"  ⚠️ Imgur falhou: {r.status_code} {r.text[:200]}")
            return None
    except Exception as e:
        print(f"  ⚠️ Erro upload Imgur: {e}")
        return None

def obter_url_foto():
    """Retorna URL pública da foto. Prioridade: hardcoded > cache > upload."""
    if FOTO_URL_PUBLICA:
        return FOTO_URL_PUBLICA
    if URL_CACHE.exists():
        url = URL_CACHE.read_text().strip()
        if url:
            return url
    if not FOTO.exists():
        print(f"  ⚠️ Foto não encontrada em {FOTO}. Pulando busca reversa.")
        return None
    return upload_para_imgur(FOTO)

def scrape_yandex_reverso(foto_url):
    """
    Faz busca reversa no Yandex com a URL da foto. Filtra resultados
    pra mostrar só os de marketplaces BR.

    Best effort: pode quebrar se Yandex bloquear ou mudar HTML.
    """
    if not foto_url:
        return []

    yandex_url = (f"https://yandex.com/images/search"
                  f"?rpt=imageview&url={quote_plus(foto_url)}")
    out = []
    try:
        r = requests.get(yandex_url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"    ⚠️ Yandex retornou {r.status_code}")
            return out

        # Yandex tem múltiplos formatos de resposta. A gente captura
        # qualquer link externo que apareça e filtra depois.
        soup = BeautifulSoup(r.text, "lxml")

        candidatos = set()

        # 1. Links diretos no HTML
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http") and "yandex." not in href:
                candidatos.add(href)

        # 2. URLs embutidas em data-attributes / JSON do HTML
        # Yandex coloca resultados num blob JSON dentro de <div class="serp-item">
        for item in soup.select("div.serp-item, div.SimilarImage"):
            data = item.get("data-bem", "") or str(item)
            urls_match = re.findall(r'https?://[^\s"\'<>]+', data)
            for u in urls_match:
                if "yandex." not in u and "mds.yandex" not in u:
                    candidatos.add(u)

        # Filtra só marketplaces BR
        for url in candidatos:
            if not eh_marketplace_br(url):
                continue
            # Limpa querystring de tracking
            url_limpa = url.split("?utm_")[0].split("&utm_")[0]
            out.append({
                "site": f"Yandex→{urlparse(url_limpa).netloc}",
                "url": url_limpa,
                "titulo": "[FOTO SIMILAR encontrada via Yandex]",
                "preco": "",
                "local": "",
                "fonte": "busca-reversa-yandex",
            })

        print(f"    ℹ️ Yandex: {len(candidatos)} candidatos, "
              f"{len(out)} em marketplaces BR")

    except Exception as e:
        print(f"    ⚠️ Yandex erro: {e}")
    return out

# ============================================================
# MAIN
# ============================================================

def check_anuncios():
    conn = init_db()
    novos = []

    # === FASE 1: PALAVRAS-CHAVE ===
    print("\n" + "=" * 60)
    print("FASE 1: BUSCA POR PALAVRAS-CHAVE")
    print("=" * 60)

    SCRAPERS = [
        ("OLX",           scrape_olx),
        ("Mercado Livre", scrape_mercado_livre),
        ("Enjoei",        scrape_enjoei),
    ]

    for query in QUERIES:
        print(f"\n🔎 '{query}'")
        for nome, scraper in SCRAPERS:
            print(f"  • {nome}...", end=" ", flush=True)
            try:
                resultados = scraper(query)
            except Exception as e:
                print(f"erro: {e}")
                continue
            print(f"{len(resultados)} resultados")
            for a in resultados:
                if ja_visto(conn, a["url"]):
                    continue
                if not passa_filtros(a["titulo"]):
                    marcar_visto(conn, a)
                    continue
                novos.append(a)
                marcar_visto(conn, a)
            time.sleep(random.uniform(3, 5))

    # === FASE 2: BUSCA REVERSA POR IMAGEM (best effort) ===
    print("\n" + "=" * 60)
    print("FASE 2: BUSCA REVERSA POR IMAGEM (Yandex)")
    print("=" * 60)

    foto_url = obter_url_foto()
    if foto_url:
        print(f"\n  🖼️ URL da foto: {foto_url}")
        print("  🔎 Consultando Yandex...")
        resultados_visuais = scrape_yandex_reverso(foto_url)
        for a in resultados_visuais:
            if ja_visto(conn, a["url"]):
                continue
            novos.append(a)
            marcar_visto(conn, a)
    else:
        print("  ⏭️ Pulando busca reversa (sem foto disponível)")

    # === FASE 3: ENVIAR ALERTAS ===
    print("\n" + "=" * 60)
    print(f"📊 RESUMO: {len(novos)} novo(s) achado(s)")
    print("=" * 60)

    # Ordena: busca reversa primeiro, depois SP, depois resto
    novos.sort(key=lambda a: (
        a.get("fonte") != "busca-reversa-yandex",
        not eh_prioritario(a.get("local", "")),
        a["site"]
    ))

    for a in novos:
        if a.get("fonte") == "busca-reversa-yandex":
            flag = "🚨🖼️ [FOTO SIMILAR] "
        elif eh_prioritario(a.get("local", "")):
            flag = "🚨 [SP/REGIÃO] "
        else:
            flag = "🔔 "

        partes = [
            f"{flag}Possível brinco encontrado!",
            "",
            f"🏪 Site: {a['site']}",
            f"📿 Título: {a['titulo']}",
        ]
        if a.get("preco"):
            partes.append(f"💰 Preço: {a['preco']}")
        if a.get("local"):
            partes.append(f"📍 Local: {a['local']}")
        partes.extend([
            "",
            f"🔗 {a['url']}",
            "",
            "⚠️ NÃO contate o vendedor. Salve print e leve à delegacia.",
        ])
        send_telegram_message("\n".join(partes))
        time.sleep(1)

    conn.close()

if __name__ == "__main__":
    check_anuncios()
