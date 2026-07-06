PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pessoas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    genero TEXT NOT NULL CHECK (genero IN ('M', 'F')),
    ativo INTEGER NOT NULL DEFAULT 1,
    telefone TEXT,
    observacoes TEXT,
    -- cônjuge (marido/esposa): permite que a dupla marido+esposa seja uma exceção
    -- válida à regra de mesmo gênero no sorteio. Vínculo simétrico mantido pela
    -- aplicação (setar A->B também seta B->A). NULL = sem cônjuge cadastrado.
    conjuge_id INTEGER REFERENCES pessoas(id),
    -- pode_dirigir: pessoa habilitada a ser dirigente de campo (saída de campo).
    -- Dirigente É uma pessoa (modelo unificado); este flag define o pool de dirigentes.
    pode_dirigir INTEGER NOT NULL DEFAULT 0
);

-- === Saída de campo (dirigente) ==========================================
-- Saída de campo é uma entidade SEPARADA do carrinho: dias e períodos são
-- livremente configuráveis por congregação (0 a 14 saídas/semana = 7 dias x
-- manhã/tarde). Cada congregação define seu próprio padrão na tela "Saídas
-- de Campo". Sorteia 1 dirigente (pessoa com pode_dirigir=1) por saída/dia.
-- Um dirigente designado numa saída no período P do dia D fica bloqueado no
-- carrinho no mesmo P/D.
CREATE TABLE IF NOT EXISTS saida_campo_template (
    saida_id TEXT PRIMARY KEY,
    dia_semana TEXT NOT NULL,
    periodo TEXT NOT NULL CHECK (periodo IN ('MANHA', 'TARDE')),
    local TEXT NOT NULL DEFAULT '',
    ordem INTEGER NOT NULL,
    vigencia_inicio TEXT NOT NULL,
    vigencia_fim TEXT,
    ativo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS saida_disponibilidade (
    pessoa_id INTEGER NOT NULL REFERENCES pessoas(id),
    saida_id TEXT NOT NULL REFERENCES saida_campo_template(saida_id),
    PRIMARY KEY (pessoa_id, saida_id)
);

CREATE TABLE IF NOT EXISTS historico_saidas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL,
    saida_id TEXT NOT NULL REFERENCES saida_campo_template(saida_id),
    dirigente_id INTEGER REFERENCES pessoas(id),
    mes_referencia TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RASCUNHO', 'FECHADO'))
);

CREATE TABLE IF NOT EXISTS slot_template (
    slot_id TEXT PRIMARY KEY,
    dia_semana TEXT NOT NULL,
    periodo TEXT NOT NULL CHECK (periodo IN ('MANHA', 'TARDE')),
    local TEXT NOT NULL,
    ordem INTEGER NOT NULL,
    requer_dirigente INTEGER NOT NULL DEFAULT 0,
    vigencia_inicio TEXT NOT NULL,
    vigencia_fim TEXT,
    ativo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS disponibilidades (
    pessoa_id INTEGER NOT NULL REFERENCES pessoas(id),
    slot_id TEXT NOT NULL REFERENCES slot_template(slot_id),
    ativo INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (pessoa_id, slot_id)
);

CREATE TABLE IF NOT EXISTS fixos (
    fixo_id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id TEXT NOT NULL REFERENCES slot_template(slot_id),
    pessoa_id_1 INTEGER NOT NULL REFERENCES pessoas(id),
    pessoa_id_2 INTEGER REFERENCES pessoas(id),
    vigencia_inicio TEXT NOT NULL,
    vigencia_fim TEXT,
    ativo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS dirigentes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS dirigentes_disponibilidade (
    dirigente_id INTEGER NOT NULL REFERENCES dirigentes(id),
    slot_id TEXT NOT NULL REFERENCES slot_template(slot_id),
    PRIMARY KEY (dirigente_id, slot_id)
);

CREATE TABLE IF NOT EXISTS bloqueios (
    bloqueio_id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_inicio TEXT NOT NULL,
    data_fim TEXT NOT NULL,
    motivo TEXT,
    ativo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS historico_carrinho (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL,
    slot_id TEXT NOT NULL REFERENCES slot_template(slot_id),
    pessoa_id_1 INTEGER REFERENCES pessoas(id),
    pessoa_id_2 INTEGER REFERENCES pessoas(id),
    origem TEXT NOT NULL CHECK (
        origem IN ('FIXO', 'SORTEIO', 'FALLBACK_PAR_REPETIDO', 'FALLBACK_DUPLICADO', 'MANUAL', 'VAZIO')
    ),
    mes_referencia TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RASCUNHO', 'FECHADO'))
);

CREATE TABLE IF NOT EXISTS historico_dirigentes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL,
    slot_id TEXT NOT NULL REFERENCES slot_template(slot_id),
    dirigente_id INTEGER REFERENCES dirigentes(id),
    mes_referencia TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RASCUNHO', 'FECHADO'))
);

-- === Configurações gerais (chave/valor) ====================================
-- nome_congregacao, idioma (ver app/i18n.py), wizard_concluido ("0"/"1").
CREATE TABLE IF NOT EXISTS configuracoes (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hist_saidas_mes ON historico_saidas (mes_referencia);
CREATE INDEX IF NOT EXISTS idx_hist_saidas_dirigente ON historico_saidas (dirigente_id);
CREATE INDEX IF NOT EXISTS idx_saida_disp_saida ON saida_disponibilidade (saida_id);
CREATE INDEX IF NOT EXISTS idx_hist_carrinho_mes ON historico_carrinho (mes_referencia);
CREATE INDEX IF NOT EXISTS idx_hist_carrinho_pessoa1 ON historico_carrinho (pessoa_id_1);
CREATE INDEX IF NOT EXISTS idx_hist_carrinho_pessoa2 ON historico_carrinho (pessoa_id_2);
CREATE INDEX IF NOT EXISTS idx_hist_dirigentes_mes ON historico_dirigentes (mes_referencia);
CREATE INDEX IF NOT EXISTS idx_disponibilidades_slot ON disponibilidades (slot_id);
CREATE INDEX IF NOT EXISTS idx_fixos_slot ON fixos (slot_id);
