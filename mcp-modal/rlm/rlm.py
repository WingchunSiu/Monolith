from abc import ABC, abstractmethod

class RLM(ABC):
    @abstractmethod
    def completion(self, context: list[str] | str | dict[str, str], query: str) -> str:
        pass

    @abstractmethod
    def cost_summary(self) -> dict[str, float]:
        pass

    @abstractmethod
    def reset(self):
        pass
