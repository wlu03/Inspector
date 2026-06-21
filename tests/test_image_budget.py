from types import SimpleNamespace

from inspector.config import Config
from inspector.session import Session


def test_image_cap_enforced():
    # image_allowed only touches self.config + self.images_returned, so a stand-in
    # object exercises the cost-cap logic without building a full live Session.
    s = SimpleNamespace(config=Config(max_images_per_session=2), images_returned=0)
    assert Session.image_allowed(s) is True   # 1st
    assert Session.image_allowed(s) is True   # 2nd
    assert Session.image_allowed(s) is False  # over the cap → text-only
    assert s.images_returned == 2


def test_zero_cap_is_unlimited():
    s = SimpleNamespace(config=Config(max_images_per_session=0), images_returned=999)
    assert Session.image_allowed(s) is True
