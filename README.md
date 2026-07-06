# Escala do Carrinho

Aplicativo desktop gratuito para gerar a escala mensal do carrinho de literatura e das saídas de campo de uma congregação — com sorteio automático, rodízio justo, cônjuges como exceção de gênero, dirigentes de campo e suporte a 30 idiomas.

## Instalação (usuário final)

Baixe o instalador `EscalaCarrinho_Setup.exe` na aba [Releases](../../releases) e execute. Não precisa de admin, não precisa instalar Python — tudo já vem empacotado. Na primeira abertura, um assistente guia a configuração inicial (nome da congregação, idioma, horários do carrinho, saídas de campo).

Veja o [Manual de Uso](Manual%20de%20Uso%20-%20Escala%20do%20Carrinho.docx) (ou o [PDF](Manual%20de%20Uso%20-%20Escala%20do%20Carrinho.pdf)) para um passo a passo com telas de todas as funções.

## Principais recursos

- Sorteio automático com rodízio (prioriza quem está há mais tempo sem servir)
- Duplas sempre do mesmo gênero, com cônjuges como exceção configurável
- Dirigentes de campo (saída de campo) sorteados separadamente do carrinho, com bloqueio automático pra não escalar a mesma pessoa nos dois ao mesmo tempo
- Pessoas fixas em horários recorrentes
- Datas bloqueadas (congressos, assembleias)
- Exportação em PDF
- Estrutura semanal 100% configurável (dias, períodos, locais) — funciona pra qualquer congregação, não só a que originou o projeto
- 30 idiomas, incluindo línguas indígenas e crioulas das Américas (guarani, crioulo haitiano, quíchua, mapudungun, navajo, entre outras)

## Rodando em modo desenvolvedor

Requer Python 3.14+.

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Testes:

```
pip install -r requirements-dev.txt
pytest
```

## Gerando o instalador

```
pyinstaller build.spec --noconfirm
ISCC installer\setup.iss
```

## Licença

MIT — veja [LICENSE](LICENSE). Uso livre por qualquer congregação.
