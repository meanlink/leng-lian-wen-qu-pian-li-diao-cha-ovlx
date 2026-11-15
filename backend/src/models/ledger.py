from sqlalchemy import String, Double, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class LedgerState(Base):
    """单行账本头：所有追加在同一事务内锁定此行，保证并发下序号唯一且连续。"""
    __tablename__ = 'ledger_state'
    id: Mapped[int] = mapped_column(primary_key=True)
    head_seq: Mapped[int] = mapped_column(Integer, default=0)
    head_hash: Mapped[str] = mapped_column(String(64), default='')
    updated_at: Mapped[float] = mapped_column(Double, default=0)
class LedgerSeal(Base):
    """封账：锁定某一高度的链头，凭据交管理员离线保存，作为核验锚点。"""
    __tablename__ = 'ledger_seals'
    id: Mapped[int] = mapped_column(primary_key=True)
    sealed_at: Mapped[float] = mapped_column(Double)
    head_seq: Mapped[int] = mapped_column(Integer)
    head_hash: Mapped[str] = mapped_column(String(64), default='')
    entries: Mapped[int] = mapped_column(Integer, default=0)
    legacy: Mapped[int] = mapped_column(Integer, default=0)
    seal_key: Mapped[str] = mapped_column(String(64), default='')
    mac: Mapped[str] = mapped_column(String(64), default='')
    file_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    file_checksum: Mapped[str] = mapped_column(String(64), default='')
    file_bytes: Mapped[int] = mapped_column(Integer, default=0)
