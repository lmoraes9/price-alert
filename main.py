import requests
from bs4 import BeautifulSoup
import json
import time
import os

# Links para verificar
URLS = [
    "https://www.obahortifruti.com.br/hydro-protein-tangerina-moving-500ml-100010009/p",
    "https://www.obahortifruti.com.br/hydro-protein-uva-moving-500ml-100010010/p",
    "https://www.obahortifruti.com.br/hydro-protein-limao-moving-500ml-100010008/p",
    "https://www.obahortifruti.com.br/moving-hydro-protein-frutas-vermelhas-500-ml-100010970/p"
]

TARGET_PRICE = 8.00

# Configurações do Telegram (Preencha se for rodar localmente, ou use Variáveis de Ambiente no servidor)
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN') 
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"Telegram não configurado. Mensagem seria: {message}")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    try:
        requests.post(url, json=payload)
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
            
            # Encontra o script JSON do Next.js (onde os dados reais estão)
            script_tag = soup.find('script', id='__NEXT_DATA__')
            
            if script_tag:
                json_data = json.loads(script_tag.string)
                
                # Navega pelo JSON conforme a estrutura do arquivo que você enviou
                try:
                    product_data = json_data['props']['pageProps']['data']['product']
                    name = product_data['name']
                    # O preço está dentro de offers -> offers[0] -> price
                    price = product_data['offers']['offers'][0]['price']
                    
                    print(f"Checando: {name} - R$ {price}")

                    if price < TARGET_PRICE:
                        msg = f"🚨 PROMOÇÃO DETECTADA!\n\nProduto: {name}\nPreço: R$ {price}\nLink: {url}"
                        send_telegram_message(msg)
                        
                except KeyError as e:
                    print(f"Erro de estrutura do JSON (site mudou?): {e} em {url}")
            else:
                print(f"Tag de dados não encontrada em {url}")

        except Exception as e:
            print(f"Erro genérico ao processar {url}: {e}")

if __name__ == "__main__":
    print("Iniciando verificação...")
    check_prices()