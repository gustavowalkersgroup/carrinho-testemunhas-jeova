from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Papel(str, Enum):
    """O que a pessoa pode fazer DENTRO de uma congregação."""

    ADMIN = "ADMIN"    # tudo, inclusive aprovar quem pede acesso àquela congregação
    EDITOR = "EDITOR"  # gera e edita escala, cadastra pessoas
    LEITOR = "LEITOR"  # só visualiza e exporta

    @property
    def pode_editar(self) -> bool:
        return self in (Papel.ADMIN, Papel.EDITOR)

    @property
    def pode_administrar(self) -> bool:
        return self is Papel.ADMIN


PAPEL_DESCRICAO = {
    Papel.ADMIN: "Administra a congregação: escala, cadastros e aprovação de novos acessos.",
    Papel.EDITOR: "Gera e edita a escala e cadastra pessoas, mas não aprova acessos.",
    Papel.LEITOR: "Apenas consulta e exporta a escala.",
}


class StatusSolicitacao(str, Enum):
    PENDENTE = "PENDENTE"
    APROVADA = "APROVADA"
    RECUSADA = "RECUSADA"


class Congregacao(BaseModel):
    id: int
    nome: str
    slug: str
    cidade: str = ""
    ativa: bool = True
    criada_em: Optional[datetime] = None


class Usuario(BaseModel):
    id: int
    email: str
    nome: str = ""
    super_admin: bool = False
    ativo: bool = True
    criado_em: Optional[datetime] = None
    ultimo_acesso_em: Optional[datetime] = None


class Membro(BaseModel):
    usuario_id: int
    congregacao_id: int
    papel: Papel
    congregacao_nome: str = ""
    congregacao_slug: str = ""


class Solicitacao(BaseModel):
    id: int
    email: str
    nome: str = ""
    congregacao_id: Optional[int] = None
    congregacao_nome_sugerida: str = ""
    congregacao_nome: str = ""  # preenchido no join, quando congregacao_id existe
    mensagem: str = ""
    status: StatusSolicitacao = StatusSolicitacao.PENDENTE
    criada_em: Optional[datetime] = None
    decidida_em: Optional[datetime] = None
    observacao_decisao: str = ""


class SessaoAtual(BaseModel):
    """O que as rotas precisam saber sobre quem está acessando agora."""

    usuario: Usuario
    congregacao: Optional[Congregacao] = None
    papel: Optional[Papel] = None
    # todas as congregações do usuário, para o seletor no topo da tela
    membros: list[Membro] = []

    @property
    def pode_editar(self) -> bool:
        if self.usuario.super_admin:
            return True
        return self.papel is not None and self.papel.pode_editar

    @property
    def pode_administrar_congregacao(self) -> bool:
        if self.usuario.super_admin:
            return True
        return self.papel is not None and self.papel.pode_administrar
