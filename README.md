# Escala do Carrinho

Gerador gratuito da escala mensal do carrinho de literatura e das saídas de campo de uma congregação — com sorteio automático, rodízio justo, cônjuges como exceção de gênero, dirigentes de campo e suporte a 30 idiomas.

Roda de dois jeitos, com o **mesmo código**:

| | **Hospedado (web)** | **Desktop (Windows)** |
|---|---|---|
| Quem usa | várias congregações, cada uma com suas pessoas | uma congregação, num computador |
| Banco | Postgres | SQLite ao lado do `.exe` |
| Acesso | login por e-mail, com aprovação | quem abrir o programa |
| Como liga | variável `DATABASE_URL` definida | nenhuma variável definida |

Sem `DATABASE_URL`, o programa é exatamente o app de desktop de sempre.

## Principais recursos

- Sorteio automático com rodízio (prioriza quem está há mais tempo sem servir)
- Duplas sempre do mesmo gênero, com cônjuges como exceção configurável
- Dirigentes de campo (saída de campo) sorteados separadamente do carrinho, com bloqueio automático pra não escalar a mesma pessoa nos dois ao mesmo tempo
- Pessoas fixas em horários recorrentes
- Datas bloqueadas (congressos, assembleias)
- Exportação em PDF
- Estrutura semanal 100% configurável (dias, períodos, locais) — funciona pra qualquer congregação
- 30 idiomas, incluindo línguas indígenas e crioulas das Américas (guarani, crioulo haitiano, quíchua, mapudungun, navajo, entre outras)

---

## Instalar no desktop (usuário final)

Baixe o instalador `EscalaCarrinho_Setup.exe` na aba [Releases](../../releases) e execute. Não precisa de admin, não precisa instalar Python. Na primeira abertura, um assistente guia a configuração inicial.

Veja o [Manual de Uso](Manual%20de%20Uso%20-%20Escala%20do%20Carrinho.docx) (ou o [PDF](Manual%20de%20Uso%20-%20Escala%20do%20Carrinho.pdf)) para um passo a passo de todas as funções.

---

## Publicar na Vercel

São cinco passos, uma vez só. O plano gratuito da Vercel e o do Neon dão conta com folga do uso de várias congregações.

### 1. Importar o repositório

Em [vercel.com/new](https://vercel.com/new), importe este repositório. A Vercel reconhece o `vercel.json` e não precisa de nenhum ajuste de build. **Não faça o Deploy ainda** — falta o banco.

### 2. Criar o banco

No projeto: aba **Storage** → **Create Database** → **Neon (Postgres)**. Ao conectar ao projeto, a Vercel injeta `DATABASE_URL` sozinha.

Confira que o valor usa a string **com pooler** (o host tem `-pooler`). Cada request serverless abre uma conexão própria; sem o pooler, o banco esgota as conexões em pouco tempo.

O schema é criado sozinho no primeiro acesso — não há migração para rodar à mão.

### 3. Definir as variáveis

Em **Settings → Environment Variables** (veja [`.env.example`](.env.example) para a lista completa):

| Variável | Valor |
|---|---|
| `SUPER_ADMIN_EMAIL` | seu e-mail — é quem aprova todo mundo |
| `SECRET_KEY` | valor aleatório longo: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `RESEND_API_KEY` | chave do [Resend](https://resend.com) (plano gratuito serve) |
| `EMAIL_FROM` | `Escala do Carrinho <onboarding@resend.dev>` até ter domínio próprio |

`SECRET_KEY` não pode mudar depois: trocar derruba todas as sessões abertas.

### 4. Deploy

Clique em **Deploy**. Ao final a Vercel mostra o endereço, algo como `https://seu-projeto.vercel.app` — é esse o link para acessar e divulgar.

### 5. Primeiro acesso

Abra o endereço, clique em **Entrar** e informe o e-mail que está em `SUPER_ADMIN_EMAIL`. Você recebe um código de 6 dígitos e entra como administrador da instalação.

Depois, em **Administração → Instalação**, crie a primeira congregação.

> **Ainda sem `RESEND_API_KEY`?** Só o `SUPER_ADMIN_EMAIL` consegue entrar, e o código aparece na própria tela (e no log da função, em **Deployments → Functions**). É a saída para destravar o primeiro acesso — mas configure o envio de e-mail antes de liberar acesso a outras pessoas, senão ninguém mais consegue entrar.

---

## Como funciona o acesso

**Não há senha.** A pessoa informa o e-mail, recebe um código de 6 dígitos e entra. Nada para criar, esquecer ou vazar.

Quem ainda não tem acesso usa **Solicitar acesso** e escolhe entre entrar numa congregação já cadastrada ou pedir uma congregação nova. O pedido cai no painel de quem pode decidir, e a pessoa recebe um e-mail quando for aprovado.

Divulgue o endereço `https://seu-projeto.vercel.app/solicitar-acesso` — ele também aparece pronto no painel administrativo.

### Perfis

Dentro de **cada** congregação:

| Perfil | Pode |
|---|---|
| **Administrador** | tudo, inclusive aprovar quem pede acesso àquela congregação |
| **Editor** | gerar e editar a escala, cadastrar pessoas |
| **Somente leitura** | consultar e exportar |

Acima deles, o **administrador da instalação** (`SUPER_ADMIN_EMAIL`): enxerga todas as congregações, cria e apaga congregações e promove outros administradores. Só ele aprova pedidos de congregação nova.

Uma pessoa pode participar de mais de uma congregação, com perfil diferente em cada uma, e alterna pelo seletor no topo da tela.

### Isolamento entre congregações

Os dados de cada congregação são separados pelo **próprio Postgres**, com Row Level Security: cada transação declara em qual congregação está trabalhando, e o banco filtra tudo — inclusive as consultas herdadas da versão desktop, que não têm filtro de congregação escrito nelas.

Não é uma escolha estética. São cerca de 160 consultas em SQL cru; bastaria **uma** sem filtro para uma congregação enxergar a outra. Com RLS, uma consulta sem filtro devolve zero linhas em vez das linhas erradas — falha fechando. As políticas usam `FORCE ROW LEVEL SECURITY`, então valem também para a aplicação, que é a dona das tabelas.

Chaves estrangeiras compostas (`congregacao_id` + id) fecham o resto: um cônjuge ou uma dupla fixa apontando para pessoa de outra congregação é recusado pelo banco, não pela aplicação. Há testes para cada uma dessas garantias em [`tests_web/`](tests_web/).

---

## Rodando em modo desenvolvedor

Requer Python 3.11+.

**Desktop (SQLite, janela nativa):**

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-desktop.txt
python main.py
```

**Modo hospedado (Postgres), localmente:**

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql://postgres@localhost:5432/escala"
export SUPER_ADMIN_EMAIL="voce@exemplo.com"
export SECRET_KEY="qualquer-coisa-em-dev"
export COOKIE_SEGURO=0             # cookie sem HTTPS
uvicorn api.index:app --reload
```

## Testes

Duas suítes, porque o modo é decidido na importação (uma variável de ambiente define se é SQLite ou Postgres):

```bash
pip install -r requirements-dev.txt

pytest tests                                    # desktop / SQLite

createdb escala_test
export DATABASE_URL_TESTE="postgresql://postgres@localhost:5432/escala_test"
pytest tests_web                                # hospedado / Postgres
```

`tests_web` é pulada quando `DATABASE_URL_TESTE` não está definida, então `pytest tests` continua bastando para mexer só no desktop.

O Postgres do teste precisa de um usuário **sem** `SUPERUSER` e **sem** `BYPASSRLS`: esses dois passam por cima das políticas de isolamento, e a suíte deixaria de testar exatamente o que deveria.

## Gerando o instalador do Windows

```bash
pip install -r requirements-desktop.txt
pyinstaller build.spec --noconfirm
ISCC installer\setup.iss
```

## Licença

MIT — veja [LICENSE](LICENSE). Uso livre por qualquer congregação.
