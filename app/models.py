from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Genero(str, Enum):
    M = "M"
    F = "F"


class Periodo(str, Enum):
    MANHA = "MANHA"
    TARDE = "TARDE"


class Origem(str, Enum):
    FIXO = "FIXO"
    SORTEIO = "SORTEIO"
    FALLBACK_PAR_REPETIDO = "FALLBACK_PAR_REPETIDO"
    FALLBACK_DUPLICADO = "FALLBACK_DUPLICADO"
    MANUAL = "MANUAL"
    VAZIO = "VAZIO"


class StatusEscala(str, Enum):
    RASCUNHO = "RASCUNHO"
    FECHADO = "FECHADO"


class PessoaIn(BaseModel):
    nome: str
    genero: Genero
    ativo: bool = True
    telefone: Optional[str] = None
    observacoes: Optional[str] = None
    conjuge_id: Optional[int] = None
    pode_dirigir: bool = False


class Pessoa(PessoaIn):
    id: int


class SlotTipoIn(BaseModel):
    slot_id: str
    dia_semana: str
    periodo: Periodo
    local: str
    ordem: int
    requer_dirigente: bool = False
    vigencia_inicio: date
    vigencia_fim: Optional[date] = None
    ativo: bool = True


class SlotTipo(SlotTipoIn):
    pass


class DisponibilidadeIn(BaseModel):
    pessoa_id: int
    slot_id: str
    ativo: bool = True


class Disponibilidade(DisponibilidadeIn):
    pass


class FixoIn(BaseModel):
    slot_id: str
    pessoa_id_1: int
    pessoa_id_2: Optional[int] = None
    vigencia_inicio: date
    vigencia_fim: Optional[date] = None
    ativo: bool = True


class Fixo(FixoIn):
    fixo_id: int


class DirigenteIn(BaseModel):
    nome: str
    ativo: bool = True


class Dirigente(DirigenteIn):
    id: int


# === Saída de campo ========================================================

class SaidaCampoTemplateIn(BaseModel):
    saida_id: str
    dia_semana: str          # SEGUNDA..DOMINGO — dias configuráveis por congregação
    periodo: Periodo
    local: str = ""
    ordem: int
    vigencia_inicio: date
    vigencia_fim: Optional[date] = None
    ativo: bool = True


class SaidaCampoTemplate(SaidaCampoTemplateIn):
    pass


class DesignacaoSaida(BaseModel):
    id: Optional[int] = None
    data: date
    saida_id: str
    dirigente_id: Optional[int] = None   # referencia pessoas(id) — dirigente É uma pessoa
    mes_referencia: str
    status: StatusEscala


class DesignacaoSaidaUpdateIn(BaseModel):
    dirigente_id: Optional[int] = None


class DirigenteDisponibilidadeIn(BaseModel):
    dirigente_id: int
    slot_id: str


class BloqueioIn(BaseModel):
    data_inicio: date
    data_fim: date
    motivo: Optional[str] = None
    ativo: bool = True


class Bloqueio(BloqueioIn):
    bloqueio_id: int


class DesignacaoCarrinho(BaseModel):
    id: Optional[int] = None
    data: date
    slot_id: str
    pessoa_id_1: Optional[int] = None
    pessoa_id_2: Optional[int] = None
    origem: Origem
    mes_referencia: str
    status: StatusEscala


class DesignacaoDirigente(BaseModel):
    id: Optional[int] = None
    data: date
    slot_id: str
    dirigente_id: Optional[int] = None
    mes_referencia: str
    status: StatusEscala


class DisponibilidadeUpdateIn(BaseModel):
    slot_ids: list[str]


class EncerrarFixoIn(BaseModel):
    data_fim: date


class DesignacaoUpdateIn(BaseModel):
    pessoa_id_1: Optional[int] = None
    pessoa_id_2: Optional[int] = None


class DesignacaoDirigenteUpdateIn(BaseModel):
    dirigente_id: Optional[int] = None


class Aviso(BaseModel):
    nivel: str  # "info" | "atencao" | "critico"
    mensagem: str  # texto fixo em pt-BR — fallback quando `chave` não é usada
    chave: Optional[str] = None  # chave de tradução em app/i18n.py (ver render_aviso)
    parametros: dict = {}
    prefixo: str = ""  # não traduzível (data/id), ex: "2026-07-05 (SLOT_A)"


class EscalaMensal(BaseModel):
    mes_referencia: str
    designacoes: list[DesignacaoCarrinho]
    designacoes_dirigentes: list[DesignacaoDirigente] = []  # legado (carrinho) — não mais preenchido
    designacoes_saidas: list[DesignacaoSaida] = []          # saída de campo (modelo novo)
    avisos: list[Aviso]
