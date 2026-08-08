# Pacote de propósito, como `tests/`: com __init__.py o pytest põe a RAIZ do
# repositório no sys.path (e não a pasta de testes), que é o que faz `import
# app` funcionar ao chamar `pytest` direto — sem isso só funciona via
# `python -m pytest`, que já inclui o diretório atual.
