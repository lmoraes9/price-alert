# Monitor de Preços → WhatsApp

Confere o preço de uma lista de produtos duas vezes por dia (8h e 20h) e manda
mensagem no WhatsApp quando algum ficar abaixo do preço alvo. Roda de graça no
GitHub Actions e usa o [CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/)
(também grátis) para mandar a mensagem.

## Configurar o WhatsApp

1. Se ainda não tiver a apikey: adicione o número do CallMeBot nos contatos e mande
   `I allow callmebot to send me messages` pra ele (o número atual está no site
   deles). Ele responde com sua apikey.
2. No GitHub: **Settings → Secrets and variables → Actions → New repository secret**:
   - `CALLMEBOT_PHONE` → seu número com DDI, ex: `+5511999998888`
   - `CALLMEBOT_APIKEY` → a apikey
3. Teste: **Actions → Monitor de Preços → Run workflow**, marque *"Só mandar uma
   mensagem de teste"* e rode.

Para avisar mais de uma pessoa, coloque os números e apikeys separados por
vírgula, na mesma ordem.

## Adicionar produtos, lojas e preços

Edite o `produtos.json` (dá pra editar direto no site do GitHub):

```json
{
  "preco_alvo_padrao": 8.00,
  "produtos": [
    { "nome": "Hydro Protein Uva", "url": "https://www.atacadao.com.br/...-uva-7337-58137/p" },
    { "nome": "Whey 900g", "url": "https://www.outraloja.com.br/whey/p", "preco_alvo": 99.90 }
  ]
}
```

- `preco_alvo` é opcional; sem ele vale o `preco_alvo_padrao`.
- `nome` e `loja` são opcionais (servem só para a mensagem).
- Funciona com Atacadão, Oba Hortifruti e, em geral, com qualquer loja que siga o
  padrão schema.org ou seja VTEX (Carrefour, Pão de Açúcar, Drogasil, Centauro…).
  Se uma loja não funcionar, o log do Actions mostra o erro.

## Como ele evita spam

O `estado.json` (atualizado automaticamente) guarda o que já foi avisado:

- avisa quando o produto **entra** em promoção ou quando o preço **cai ainda mais**;
- se o preço voltar acima do alvo e depois cair de novo, avisa de novo;
- se não conseguir ler um produto 3 vezes seguidas, avisa uma vez (o link
  provavelmente mudou).

## Rodar localmente

```bash
pip install -r requirements.txt
python main.py            # sem secrets, só imprime a mensagem no terminal
python main.py --teste    # manda mensagem de teste (precisa das variáveis CALLMEBOT_*)
```
