# Radar de Lançamentos

Monitor automático de lançamentos de livros de teoria em direito, política, sociologia, filosofia, psicanálise, história e áreas próximas. Ele lê os sites das editoras todos os dias, guarda os livros novos num catálogo público e manda um resumo semanal por e-mail para quem se inscrever, só com as áreas que cada pessoa escolheu.

Site: https://pedrosayeg.github.io/Radar-de-Lancamentos/ (depois de ativar o GitHub Pages, ver abaixo)

## Como funciona

1. Todo dia às 8h17 (Brasília), o GitHub roda o robô (`.github/workflows/radar.yml`).
2. O robô lê cada editora listada em `config/fontes.yaml`. Dependendo do tipo de loja, ele usa a API pública da loja (Shopify, WooCommerce, VTEX) ou compara o sitemap do site com a leitura anterior para achar páginas de produto novas.
3. Os livros novos são classificados por área. Com a chave da API da Anthropic configurada, quem classifica é o Claude, que também descarta ficção, infantil, autoajuda e afins. Sem a chave, o robô usa palavras-chave, o que funciona razoavelmente para editoras especializadas e mal para editoras generalistas.
4. O catálogo (`data/livros.json`) e o site (`docs/`) são atualizados e publicados.
5. No dia da semana configurado (padrão segunda-feira), sai o e-mail com tudo o que entrou desde o último envio.

Na primeira leitura de cada editora o robô só registra o catálogo existente como base. Entram no site apenas livros com data de lançamento conhecida nos últimos 30 dias ou em pré-venda. A partir da segunda leitura, todo produto novo é considerado lançamento. Por isso o site começa pequeno e vai crescendo nas primeiras semanas.

## Configuração (uma vez só)

### 1. Ativar o site

No repositório, vá em **Settings > Pages** e, em "Build and deployment", escolha **Source: GitHub Actions**.

### 2. Cadastrar os segredos

Em **Settings > Secrets and variables > Actions > New repository secret**, crie os que for usar. Nenhum deles fica visível no código.

| Segredo | Para que serve | Obrigatório |
|---|---|---|
| `ANTHROPIC_API_KEY` | Classificação por IA (recomendado). Gere em console.anthropic.com. É cobrada à parte da assinatura do Claude. | Não, mas melhora muito a qualidade |
| `BREVO_API_KEY` | Envio dos e-mails pelo Brevo | Sim, para e-mail via Brevo |
| `BREVO_LIST_ID` | Número da lista de inscritos no Brevo | Sim, para e-mail via Brevo |
| `REMETENTE_EMAIL` | E-mail que aparece como remetente (precisa estar verificado no Brevo) | Sim, para qualquer e-mail |
| `ADMIN_EMAIL` | Seu e-mail, para receber alertas quando uma editora parar de funcionar | Não |
| `BREVO_ATRIBUTO_AREAS` | Nome do atributo de contato com as áreas escolhidas (padrão `AREAS`) | Não |

Alternativa sem Brevo: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USUARIO`, `SMTP_SENHA`, `REMETENTE_EMAIL` e `DESTINATARIOS` (formato `email1|Direito,Filosofia;email2;email3|História`, sem áreas significa todas).

### 3. Montar a inscrição no Brevo

1. Crie uma conta gratuita em brevo.com e verifique o e-mail remetente.
2. Em **Contacts > Settings > Contact attributes**, crie o atributo `AREAS` do tipo **Multiple-choice**, com exatamente estas opções: Direito, Política, Sociologia, Filosofia, Psicanálise, História, Economia, Antropologia, Outras humanidades.
3. Crie uma lista (por exemplo "Radar de Lançamentos") e anote o número dela, que vai no segredo `BREVO_LIST_ID`.
4. Em **Contacts > Forms**, crie um formulário de inscrição com os campos e-mail e AREAS, ligado a essa lista. Copie o link público do formulário.
5. Cole esse link em `url_inscricao`, no arquivo `config/geral.yaml`. O botão "Receber por e-mail" do site passa a apontar para ele.
6. Gere a chave da API em **SMTP & API > API keys** e salve como `BREVO_API_KEY`.

Quem não marcar nenhuma área recebe todas.

## Uso no dia a dia

- **Rodar agora**: aba **Actions > Radar de Lançamentos > Run workflow**. Marque "Enviar o e-mail agora" se quiser disparar o resumo fora do dia normal.
- **Adicionar uma editora**: edite `config/fontes.yaml`. Para descobrir o tipo de loja, rode `python -m radar.diagnostico https://site-da-editora.com.br`.
- **Desligar uma editora**: coloque `ativo: false` no bloco dela.
- **Mudar dia do e-mail, áreas ou textos**: `config/geral.yaml`.
- **Ver se alguma editora quebrou**: no rodapé do site há a tabela "Editoras monitoradas e situação da última leitura".

## Limitações conhecidas

- Ler sites de editoras é frágil. Se uma editora mudar o site, a leitura dela pode falhar até alguém ajustar a configuração. O robô registra a falha e, com `ADMIN_EMAIL` configurado, avisa depois de 3 falhas seguidas.
- Editoras que não têm loja própria, que bloqueiam leitura automática ou que só vendem por marketplaces não estão cobertas. A D'Plácido está desativada por esse motivo.
- A classificação por área é automática e pode errar, principalmente sem a chave da Anthropic.
- "Produto novo no site" nem sempre é lançamento. Pode ser reimpressão, nova edição ou um item que a editora só agora cadastrou.
- O plano gratuito do Brevo permite 300 e-mails por dia. Para um grupo de amigos isso sobra.

## Rodar no próprio computador

```
pip install -r requirements.txt
python -m radar.main --sem-envio
```
