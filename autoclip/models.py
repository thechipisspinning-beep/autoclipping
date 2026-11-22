from dataclasses import dataclass, field


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Segment:
    """Una frase/riga del transcript, con le parole e i loro tempi."""
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Clip:
    start: float
    end: float
    title: str = ""
    hook: str = ""
    reason: str = ""
    score: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start
