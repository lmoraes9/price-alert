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
