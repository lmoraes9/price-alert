"""
import requests
from bs4 import BeautifulSoup
import json
import os

# Links do Oba Hortifruti
OBA_URLS =[
    "https://www.obahortifruti.com.br/hydro-protein-tangerina-moving-500ml-100010009/p",
    "https://www.obahortifruti.com.br/hydro-protein-uva-moving-500ml-100010010/p",
    "https://www.obahortifruti.com.br/hydro-protein-limao-moving-500ml-100010008/p",
    "https://www.obahortifruti.com.br/moving-hydro-protein-frutas-vermelhas-500-ml-100010970/p"
]

# Links do Atacadão
ATACADAO_URLS =[
    "https://www.atacadao.com.br/suplemento-alimentar-hydro-protein-tangerina-7335-58136/p",
    "https://www.atacadao.com.br/suplemento-alimentar-hydro-protein-frutas-vermelhas-9555-59217/p",
    "https://www.atacadao.com.br/suplemento-alimentar-hydro-protein-uva-7337-58137/p",
    "https://www.atacadao.com.br/suplemento-alimentar-hydro-protein-limao-7339-58138/p"
]

# Junta todas as listas para o robô checar
URLS = OBA_URLS + ATACADAO_URLS

# Preço alvo (abaixo de 8 reais)
TARGET_PRICE = 8.00

# Pega as senhas das configurações do GitHub (Secrets)
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN') 
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"Telegram não configurado. Mensagem seria:\n{message}")
        return
    
    # Suporte para múltiplos IDs caso você tenha usado a opção de enviar para mais de uma pessoa
    chat_ids_list = TELEGRAM_CHAT_ID.split(',')

    for chat_id in chat_ids_list:
        chat_id_clean = chat_id.strip()
        if not chat_id_clean: continue

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id_clean,
            "text": message
        }
        try:
            requests.post(url, json=payload)
            print(f"Mensagem enviada para {chat_id_clean}!")
        except Exception as e:
            print(f"Erro ao enviar telegram: {e}")

def check_prices():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    for url in URLS:
        try:
            response = requests.get(url, headers=headers)
            
            if response.status_code != 200:
                print(f"Erro ao acessar {url}: Status {response.status_code}")
                continue

            soup = BeautifulSoup(response.content, 'html.parser')
            script_tag = soup.find('script', id='__NEXT_DATA__')
            
            if script_tag:
                json_data = json.loads(script_tag.string)
                
                try:
                    # Lógica para ler o site do Oba Hortifruti
                    if "obahortifruti.com.br" in url:
                        product_data = json_data['props']['pageProps']['data']['product']
                        name = product_data['name']
                        price = product_data['offers']['offers'][0]['price']
                        loja = "Oba Hortifruti"
                        
                    # Lógica para ler o site do Atacadão
                    elif "atacadao.com.br" in url:
                        product_data = json_data['props']['pageProps']['product']
                        name = product_data['name']
                        # Pega o 'lowPrice' (preço de atacado)
                        price = product_data['offers']['lowPrice']
                        loja = "Atacadão"
                        
                    else:
                        print(f"Loja não reconhecida: {url}")
                        continue
                    
                    print(f"Checando [{loja}]: {name} - R$ {price}")

                    # Dispara o alerta se for menor que R$ 8,00
                    if price < TARGET_PRICE:
                        msg = f"🚨 PROMOÇÃO DETECTADA!\n\n🏪 Loja: {loja}\n🛒 Produto: {name}\n💰 Preço: R$ {price}\n🔗 Link: {url}"
                        send_telegram_message(msg)
                        
                except KeyError as e:
                    print(f"Erro de estrutura do JSON em {url}: {e}")
            else:
                print(f"Tag de dados não encontrada em {url}")

        except Exception as e:
            print(f"Erro genérico ao processar {url}: {e}")

if __name__ == "__main__":
    check_prices() 
    """
"""
Monitor de Brinco Roubado — versão Telegram
=============================================
Drop-in replacement do script anterior. Usa os MESMOS secrets do GitHub:
  - TELEGRAM_TOKEN
  - TELEGRAM_CHAT_ID

Vasculha OLX, Mercado Livre e Enjoei em busca de anúncios novos que
combinem com a descrição do brinco. Manda alerta no Telegram só quando
houver coisa nova (filtra bijuteria/zircônia/folheado automaticamente).

Não precisa configurar nada novo no GitHub. Só colar este arquivo por
cima do antigo e o workflow existente continua rodando normalmente.
"""

import os
import sqlite3
import time
import random
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIGURAÇÃO — você edita ESTA seção
# ============================================================

# Palavras-chave de busca. Quanto mais específico, menos ruído.
QUERIES = [
    "brinco flor diamante ouro branco",
    "brinco diamante 4 petalas",
    "brinco flor brilhante ouro branco",
    "brinco navete diamante",
    "brinco cluster diamante ouro branco",
    # Se descobrir a marca, adicione: "brinco vivara estrela diamante"
]

# Só me avisa se o título tiver pelo menos UMA destas palavras
PALAVRAS_OBRIGATORIAS = ["diamante", "brilhante", "ouro branco", "flor",
                         "petala", "pétala"]

# Ignora anúncios óbvios de bijuteria
PALAVRAS_EXCLUIR = ["zirconia", "zircônia", "folheado", "banhado",
                    "bijuteria", "infantil", "criança", "imitação",
                    "fantasia", "prata"]

# Cidades que recebem prioridade no alerta (anúncio aqui = mais suspeito)
CIDADES_PRIORITARIAS = ["sao paulo", "são paulo", "sp", "guarulhos",
                        "osasco", "santo andre", "santo andré"]

# ============================================================
# CREDENCIAIS — vêm dos GitHub Secrets que você JÁ tem
# ============================================================

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DB = Path(__file__).parent / "anuncios_vistos.db"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_message(message):
    """Mesma lógica do seu script antigo — suporta múltiplos chat IDs."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"Telegram não configurado. Mensagem seria:\n{message}")
        return

    chat_ids_list = TELEGRAM_CHAT_ID.split(",")
    for chat_id in chat_ids_list:
        chat_id_clean = chat_id.strip()
        if not chat_id_clean:
            continue
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id_clean,
            "text": message,
            "disable_web_page_preview": False,
        }
        try:
            requests.post(url, json=payload, timeout=10)
            print(f"✅ Mensagem enviada para {chat_id_clean}")
        except Exception as e:
            print(f"⚠️ Erro ao enviar telegram: {e}")

# ============================================================
# BANCO DE DADOS — não te avisa duas vezes do mesmo anúncio
# ============================================================

def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vistos (
            url TEXT PRIMARY KEY,
            site TEXT, titulo TEXT, preco TEXT,
            local TEXT, visto_em TEXT
        )
    """)
    conn.commit()
    return conn

def ja_visto(conn, url):
    return conn.execute("SELECT 1 FROM vistos WHERE url = ?", (url,)).fetchone() is not None

def marcar_visto(conn, a):
    conn.execute(
        "INSERT OR IGNORE INTO vistos VALUES (?, ?, ?, ?, ?, ?)",
        (a["url"], a["site"], a["titulo"], a["preco"], a["local"],
         datetime.now().isoformat())
    )
    conn.commit()

# ============================================================
# FILTROS
# ============================================================

def passa_filtros(titulo):
    texto = titulo.lower()
    if any(p in texto for p in PALAVRAS_EXCLUIR):
        return False
    if not any(p in texto for p in PALAVRAS_OBRIGATORIAS):
        return False
    return True

def eh_prioritario(local):
    if not local:
        return False
    return any(c in local.lower() for c in CIDADES_PRIORITARIAS)

# ============================================================
# SCRAPERS
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
            })
    except Exception as e:
        print(f"  ⚠️ OLX erro: {e}")
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
            })
    except Exception as e:
        print(f"  ⚠️ ML erro: {e}")
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
                "preco": "", "local": "",
            })
    except Exception as e:
        print(f"  ⚠️ Enjoei erro: {e}")
    return out

# ============================================================
# MAIN
# ============================================================

def check_anuncios():
    conn = init_db()
    novos = []

    SCRAPERS = [
        ("OLX",           scrape_olx),
        ("Mercado Livre", scrape_mercado_livre),
        ("Enjoei",        scrape_enjoei),
    ]

    for query in QUERIES:
        print(f"\n🔎 Buscando: '{query}'")
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
                    marcar_visto(conn, a)  # marca pra não reprocessar
                    continue
                novos.append(a)
                marcar_visto(conn, a)

            time.sleep(random.uniform(3, 5))

    print(f"\n📊 Novos relevantes: {len(novos)}")

    # Manda uma mensagem por anúncio (priorizando SP no topo)
    novos.sort(key=lambda a: (not eh_prioritario(a["local"]), a["site"]))

    for a in novos:
        flag = "🚨 [SP/REGIÃO] " if eh_prioritario(a["local"]) else "🔔 "
        msg_parts = [
            f"{flag}Possível brinco encontrado!",
            "",
            f"🏪 Site: {a['site']}",
            f"📿 Título: {a['titulo']}",
        ]
        if a["preco"]:
            msg_parts.append(f"💰 Preço: {a['preco']}")
        if a["local"]:
            msg_parts.append(f"📍 Local: {a['local']}")
        msg_parts.append("")
        msg_parts.append(f"🔗 {a['url']}")
        msg_parts.append("")
        msg_parts.append("⚠️ NÃO contate o vendedor. Salve print e leve à delegacia.")

        send_telegram_message("\n".join(msg_parts))
        time.sleep(1)  # evita flood do Telegram

    conn.close()

if __name__ == "__main__":
    check_anuncios()
