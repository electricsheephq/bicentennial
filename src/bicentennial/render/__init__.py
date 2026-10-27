"""Template-voiced rendering of world events: phrase bank, locked tokens, dates and stamps."""

from .dates import channel_stamp as channel_stamp
from .dates import relative_date as relative_date
from .phrasebank import default_bank as default_bank
from .phrasebank import load as load
from .template import Render as Render
from .template import Slot as Slot
from .template import render_event as render_event
