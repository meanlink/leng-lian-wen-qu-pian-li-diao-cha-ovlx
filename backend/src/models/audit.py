from sqlalchemy import String, Double, JSON, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Audit(Base):
    __tablename__ = 'audits'
    __table_args__ = (UniqueConstraint('seq', name='uq_audits_seq'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(150))
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[float] = mapped_column(Double)
    # 链式留痕字段：seq 为全账唯一序号；kind='legacy' 表示建链前的未认证历史，不参与核验
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), default='', server_default='')
    entry_hash: Mapped[str] = mapped_column(String(64), default='', server_default='')
    kind: Mapped[str] = mapped_column(String(16), default='legacy', server_default='legacy')
