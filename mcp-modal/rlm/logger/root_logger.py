"""
Root (colorful) logger for RLM client that tracks model outputs and message changes.
"""

from typing import List, Dict
from datetime import datetime


class ColorfulLogger:
    """
    A colorful logger that tracks RLM client interactions with the model.
    """
    
    # ANSI color codes
    COLORS = {
        'RESET': '\033[0m',
        'BOLD': '\033[1m',
        'DIM': '\033[2m',
        'RED': '\033[31m',
        'GREEN': '\033[32m',
        'YELLOW': '\033[33m',
        'BLUE': '\033[34m',
        'MAGENTA': '\033[35m',
        'CYAN': '\033[36m',
        'WHITE': '\033[37m',
        'BG_RED': '\033[41m',
        'BG_GREEN': '\033[42m',
        'BG_YELLOW': '\033[43m',
        'BG_BLUE': '\033[44m',
        'BG_MAGENTA': '\033[45m',
        'BG_CYAN': '\033[46m',
    }
    
    def __init__(self, enabled: bool = True):
        """
        Initialize the colorful logger.
        
        Args:
            enabled: Whether console logging is enabled
        """
        self.enabled = enabled
        self.conversation_step = 0
        self.last_messages_length = 0
        self.current_query = ""
        self.session_start_time = None
        self.current_depth = 0
        
    def _colorize(self, text: str, color: str) -> str:
        """Apply color to text if logging is enabled."""
        if not self.enabled:
            return text
        return f"{self.COLORS[color]}{text}{self.COLORS['RESET']}"
    
    def _print_separator(self, char: str = "=", color: str = "CYAN"):
        """Print a colored separator line."""
        if self.enabled:
            separator = char * 80
            print(self._colorize(separator, color))
    
    def log_query_start(self, query: str):
        """Log the start of a new query."""
        if not self.enabled:
            return
            
        self.current_query = query
        self.conversation_step = 0
        self.last_messages_length = 0
        self.session_start_time = datetime.now()
        self.current_depth = 0
        
        self._print_separator("=", "GREEN")
        print(self._colorize("STARTING NEW QUERY", "BOLD") + self._colorize(" | ", "DIM") + 
              self._colorize(datetime.now().strftime("%H:%M:%S"), "DIM"))
        self._print_separator("=", "GREEN")
        
        print(self._colorize("QUERY:", "BOLD") + f" {query}")
        print()
    
    def log_initial_messages(self, messages: List[Dict[str, str]]):
        """Log the initial messages setup."""
        if not self.enabled:
            return
            
        print(self._colorize("INITIAL MESSAGES SETUP:", "BOLD"))
        for i, msg in enumerate(messages):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            
            # Truncate very long content for readability
            if len(content) > 2000:
                content = content[:2000] + "..."
            
            role_color = "BLUE" if role == "user" else "MAGENTA" if role == "assistant" else "YELLOW"
            print(f"  {self._colorize(f'[{i+1}] {role.upper()}:', role_color)} {content}")
        
        print()
        self.last_messages_length = len(messages)
    
    def log_model_response(self, response: str, has_tool_calls: bool):
        """Log the model's response."""
        if not self.enabled:
            return
            
        self.conversation_step += 1
        
        print(self._colorize(f"MODEL RESPONSE (Step {self.conversation_step}):", "BOLD"))
        
        # Truncate very long responses for readability
        display_response = response
        if len(response) > 500:
            display_response = response[:500] + "..."
        
        print(f"  {self._colorize('Response:', 'CYAN')} {display_response}")
        
        if has_tool_calls:
            print(self._colorize("  Contains tool calls - will execute them", "YELLOW"))
        else:
            print(self._colorize("  No tool calls - final response", "GREEN"))
        
        print()
    
    def log_tool_execution(self, tool_call_str: str, tool_result: str):
        """Log tool execution and result."""
        if not self.enabled:
            return
            
        print(self._colorize("TOOL EXECUTION:", "BOLD"))
        print(f"  {self._colorize('Call:', 'YELLOW')} {tool_call_str}")
        
        # Truncate very long results for readability
        display_result = tool_result
        if len(tool_result) > 300:
            display_result = tool_result[:300] + "..."
        
        print(f"  {self._colorize('Result:', 'GREEN')} {display_result}")
        print()
    
    def log_final_response(self, response: str):
        """Log the final response from the model."""
        if not self.enabled:
            return
            
        self._print_separator("=", "GREEN")
        print(self._colorize("FINAL RESPONSE:", "BOLD"))
        self._print_separator("=", "GREEN")
        print(response)
        self._print_separator("=", "GREEN")
        print() 