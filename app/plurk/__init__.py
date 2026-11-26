from app.clock import Clock
from app.config import Settings
from app.plurk.client import PlurkClient


def buat_plurk(settings: Settings, clock: Clock) -> PlurkClient:
    """FakePlurk (file data/fakeplurk.db) di mode fake, RealPlurk di mode real."""
    if settings.plurk_mode == "fake":
        from app.plurk.fake import FakePlurk

        return FakePlurk(clock, str(settings.data_dir / "fakeplurk.db"))
    from app.plurk.real import RealPlurk

    return RealPlurk(settings)
