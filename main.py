"""
Monitor de Preços -> WhatsApp (CallMeBot)
=========================================
Lê a lista de produtos em `produtos.json`, confere o preço de cada um e manda
uma mensagem no WhatsApp quando algum ficar abaixo do preço alvo.

Secrets necessários (GitHub > Settings > Secrets and variables > Actions):
  - CALLMEBOT_PHONE   seu número com DDI, ex: +5511999998888
  - CALLMEBOT_APIKEY  a apikey que o CallMeBot te mandou

Para avisar mais de uma pessoa, separe por vírgula nos dois secrets, na mesma
ordem (ex: PHONE="+5511...,+5521..." e APIKEY="123456,654321").

Para não encher o saco, o script guarda o estado em `estado.json`:
  - só avisa quando o produto ENTRA em promoção, ou quando o preço cai
    ainda mais;
  - se a página de um produto falhar 3 vezes seguidas, avisa uma vez
    (provavelmente o link mudou ou o site mudou o layout).

Uso:
  python main.py           # checa os preços
  python main.py --teste   # só manda uma mensagem de teste no WhatsApp
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent
PRODUTOS_FILE = BASE_DIR / "produtos.json"
ESTADO_FILE = BASE_DIR / "estado.json"

FALHAS_PARA_AVISAR = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

NOMES_LOJAS = {
    "atacadao.com.br": "Atacadão",
    "obahortifruti.com.br": "Oba Hortifruti",
}


# ============================================================
# WhatsApp (CallMeBot)
# ============================================================

def destinatarios():
    phones = [p.strip() for p in os.getenv("CALLMEBOT_PHONE", "").split(",") if p.strip()]
    keys = [k.strip() for k in os.getenv("CALLMEBOT_APIKEY", "").split(",") if k.strip()]
    if len(phones) != len(keys):
        print("⚠️  CALLMEBOT_PHONE e CALLMEBOT_APIKEY têm quantidades diferentes de itens.")
    return list(zip(phones, keys))


def send_whatsapp(message):
    dest = destinatarios()
    if not dest:
        print(f"WhatsApp não configurado. Mensagem seria:\n{message}\n")
        return

    for phone, apikey in dest:
        try:
            resp = requests.get(
                "https://api.callmebot.com/whatsapp.php",
                params={"phone": phone, "text": message, "apikey": apikey},
                timeout=30,
            )
            if resp.ok:
                print(f"Mensagem enviada para {phone[:-4]}****")
            else:
                print(f"Erro do CallMeBot ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            print(f"Erro ao enviar WhatsApp: {e}")
        # O CallMeBot não gosta de mensagens muito seguidas
        time.sleep(3)


# ============================================================
# Leitura de preço
# ============================================================

def to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("R$", "").strip()
    if "," in s:  # formato brasileiro: 1.234,56
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def preco_de_offers(offers):
    """Extrai o menor preço de um bloco `offers` no formato schema.org."""
    if not offers:
        return None
    if isinstance(offers, list):
        precos = [preco_de_offers(o) for o in offers]
        precos = [p for p in precos if p]
        return min(precos) if precos else None
    # lowPrice = preço de atacado no Atacadão
    for key in ("lowPrice", "price"):
        p = to_float(offers.get(key))
        if p:
            return p
    return preco_de_offers(offers.get("offers"))


def via_next_data(soup):
    """Sites VTEX FastStore (Atacadão, Oba) guardam o produto no __NEXT_DATA__."""
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        return None, None
    data = json.loads(tag.string)
    page_props = data.get("props", {}).get("pageProps", {})
    candidatos = [
        page_props.get("product"),
        (page_props.get("data") or {}).get("product"),
    ]
    for product in candidatos:
        if isinstance(product, dict):
            preco = preco_de_offers(product.get("offers"))
            if preco:
                return product.get("name"), preco
    return None, None


def via_json_ld(soup):
    """Padrão schema.org usado pela maioria das lojas online."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        itens = data if isinstance(data, list) else data.get("@graph", [data])
        for item in itens:
            if not isinstance(item, dict):
                continue
            tipo = item.get("@type")
            if tipo == "Product" or (isinstance(tipo, list) and "Product" in tipo):
                preco = preco_de_offers(item.get("offers"))
                if preco:
                    return item.get("name"), preco
    return None, None


def via_meta(soup):
    """Último recurso: meta tags de preço."""
    for attrs in (
        {"property": "product:price:amount"},
        {"property": "og:price:amount"},
        {"itemprop": "price"},
    ):
        tag = soup.find(attrs=attrs)
        if tag:
            preco = to_float(tag.get("content") or tag.get_text())
            if preco:
                titulo = soup.find("meta", property="og:title")
                return (titulo.get("content") if titulo else None), preco
    return None, None


def via_vtex_api(url):
    """Lojas VTEX (links terminando em /p) têm uma API pública de catálogo."""
    parsed = urlparse(url)
    m = re.match(r"^/(.+)/p/?$", parsed.path)
    if not m:
        return None, None
    api = f"{parsed.scheme}://{parsed.netloc}/api/catalog_system/pub/products/search/{m.group(1)}/p"
    resp = requests.get(api, headers=HEADERS, timeout=30)
    if not resp.ok:
        return None, None
    data = resp.json()
    if not data:
        return None, None
    produto = data[0]
    precos = [
        seller["commertialOffer"]["Price"]
        for item in produto.get("items", [])
        for seller in item.get("sellers", [])
        if seller.get("commertialOffer", {}).get("AvailableQuantity", 0) > 0
        and seller["commertialOffer"].get("Price")
    ]
    return (produto.get("productName"), min(precos)) if precos else (None, None)


def buscar_preco(url):
    """Retorna (nome, preco). Lança exceção se não conseguir."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "lxml")

    for estrategia in (via_next_data, via_json_ld, via_meta):
        try:
            nome, preco = estrategia(soup)
        except Exception as e:
            print(f"  ({estrategia.__name__} falhou: {e})")
            continue
        if preco:
            return nome, preco

    nome, preco = via_vtex_api(url)
    if preco:
        return nome, preco

    raise ValueError("preço não encontrado na página")


def nome_loja(url):
    host = urlparse(url).netloc.removeprefix("www.")
    for dominio, nome in NOMES_LOJAS.items():
        if host.endswith(dominio):
            return nome
    return host


def brl(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ============================================================
# Principal
# ============================================================

def carregar_json(path, padrao):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return padrao


def check_prices():
    config = carregar_json(PRODUTOS_FILE, {})
    produtos = config.get("produtos", [])
    alvo_padrao = config.get("preco_alvo_padrao")
    estado = carregar_json(ESTADO_FILE, {})

    promocoes = []
    quebrados = []

    for produto in produtos:
        url = produto["url"]
        alvo = produto.get("preco_alvo", alvo_padrao)
        loja = produto.get("loja") or nome_loja(url)
        info = estado.setdefault(url, {})

        if alvo is None:
            print(f"Sem preço alvo para {url}, pulando.")
            continue

        try:
            nome_site, preco = buscar_preco(url)
        except Exception as e:
            info["falhas"] = info.get("falhas", 0) + 1
            print(f"❌ [{loja}] {produto.get('nome', url)}: {e} (falha {info['falhas']})")
            if info["falhas"] == FALHAS_PARA_AVISAR:
                quebrados.append(f"• {produto.get('nome', url)} ({loja})\n  {url}")
            continue

        nome = produto.get("nome") or nome_site or url
        info["falhas"] = 0
        info["ultimo_preco"] = preco
        info["checado_em"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
        print(f"[{loja}] {nome}: {brl(preco)} (alvo {brl(alvo)})")

        if preco < alvo:
            ja_avisado = info.get("preco_avisado")
            if ja_avisado is None or preco < ja_avisado:
                promocoes.append(f"🛒 {nome}\n🏪 {loja}\n💰 {brl(preco)} (alvo {brl(alvo)})\n🔗 {url}")
                info["preco_avisado"] = preco
        else:
            # Saiu da promoção: na próxima vez que entrar, avisa de novo
            info.pop("preco_avisado", None)

    # Limpa do estado os produtos que saíram da lista
    urls_atuais = {p["url"] for p in produtos}
    for url in list(estado):
        if url not in urls_atuais:
            del estado[url]

    if promocoes:
        send_whatsapp("🚨 *PROMOÇÃO DETECTADA!*\n\n" + "\n\n".join(promocoes))
    if quebrados:
        send_whatsapp(
            "⚠️ Não consegui ler o preço destes produtos nas últimas "
            f"{FALHAS_PARA_AVISAR} tentativas. Talvez o link tenha mudado:\n\n"
            + "\n\n".join(quebrados)
        )
    if not promocoes:
        print("Nenhuma promoção nova.")

    ESTADO_FILE.write_text(
        json.dumps(estado, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    if "--teste" in sys.argv:
        send_whatsapp("✅ Teste do monitor de preços: o WhatsApp está funcionando!")
    else:
        check_prices()
