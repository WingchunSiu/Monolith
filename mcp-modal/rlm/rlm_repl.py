"""
Simple Recursive Language Model (RLM) with REPL environment.
"""

from typing import Dict, List, Optional, Any

from rlm import RLM
from rlm.repl import REPLEnv
from rlm.utils.llm import OpenAIClient
from rlm.utils.prompts import DEFAULT_QUERY, next_action_prompt, build_system_prompt
import rlm.utils.utils as utils

from rlm.logger.root_logger import ColorfulLogger
from rlm.logger.repl_logger import REPLEnvLogger


class RLM_REPL(RLM):
    """
    LLM Client that can handle long contexts by recursively calling itself.
    """
    
    def __init__(self, 
                 api_key: Optional[str] = None, 
                 model: str = "gpt-5",
                 recursive_model: str = "gpt-5",
                 max_iterations: int = 20,
                 depth: int = 0,
                 enable_logging: bool = False,
                 sub_rlm_mode: str = "local",
                 sandbox_app: Any = None,
                 sandbox_image: Any = None,
                 sandbox_volumes: Optional[dict[str, Any]] = None,
                 sandbox_workdir: Optional[str] = None,
                 env_file_path: Optional[str] = None,
                 sub_rlm_timeout: int = 300,
                 ):
        self.api_key = api_key
        self.model = model
        self.recursive_model = recursive_model
        self.llm = OpenAIClient(api_key, model) # Replace with other client
        
        # Track recursive call depth to prevent infinite loops
        self.repl_env = None
        self.depth = depth # Unused in this version.
        self._max_iterations = max_iterations
        self.sub_rlm_mode = sub_rlm_mode
        self.sandbox_app = sandbox_app
        self.sandbox_image = sandbox_image
        self.sandbox_volumes = sandbox_volumes
        self.sandbox_workdir = sandbox_workdir
        self.env_file_path = env_file_path
        self.sub_rlm_timeout = sub_rlm_timeout
        
        # Initialize colorful logger
        self.logger = ColorfulLogger(enabled=enable_logging)
        self.repl_env_logger = REPLEnvLogger(enabled=enable_logging)
        
        self.messages = [] # Initialize messages list
        self.query = None
    
    def setup_context(
        self,
        context: Optional[List[str] | str | List[Dict[str, str]]] = None,
        query: Optional[str] = None,
        context_path: Optional[str] = None,
    ):
        """
        Setup the context for the RLMClient.

        Args:
            context: The large context to analyze in the form of a list of messages, string, or Dict
            query: The user's question
        """
        if query is None:
            query = DEFAULT_QUERY

        self.query = query
        self.logger.log_query_start(query)

        # Initialize the conversation with the REPL prompt
        self.messages = build_system_prompt()
        self.logger.log_initial_messages(self.messages)
        
        # Initialize REPL environment with context data
        if context_path is None and context is None:
            raise ValueError("Either context or context_path must be provided.")

        context_data, context_str = utils.convert_context_for_repl(context)
        
        self.repl_env = REPLEnv(
            context_json=context_data, 
            context_str=context_str, 
            context_path=context_path,
            recursive_model=self.recursive_model,
            sub_rlm_mode=self.sub_rlm_mode,
            sandbox_app=self.sandbox_app,
            sandbox_image=self.sandbox_image,
            sandbox_volumes=self.sandbox_volumes,
            sandbox_workdir=self.sandbox_workdir,
            env_file_path=self.env_file_path,
            sub_rlm_timeout=self.sub_rlm_timeout,
        )
        
        return self.messages

    def completion(
        self,
        context: Optional[List[str] | str | List[Dict[str, str]]] = None,
        query: Optional[str] = None,
        context_path: Optional[str] = None,
    ) -> str:
        """
        Given a query and a (potentially long) context, recursively call the LM
        to explore the context and provide an answer using a REPL environment.
        """
        self.messages = self.setup_context(context, query, context_path=context_path)
        effective_query = self.query or DEFAULT_QUERY
        
        # Main loop runs for fixed # of root LM iterations
        for iteration in range(self._max_iterations):
            
            # Query root LM to interact with REPL environment
            response = self.llm.completion(self.messages + [next_action_prompt(effective_query, iteration)])
            
            # Check for code blocks
            code_blocks = utils.find_code_blocks(response)
            self.logger.log_model_response(response, has_tool_calls=bool(code_blocks))

            # Always add assistant response to message history
            self.messages.append({"role": "assistant", "content": response})

            if code_blocks:
                # Execute code and append results to messages
                self.messages = utils.process_code_execution(
                    response, self.messages, self.repl_env,
                    self.repl_env_logger, self.logger
                )
                # Don't check for FINAL() when code was executed —
                # model should see execution results before concluding
                continue

            # Only check for final answer in text-only responses (no code)
            final_answer = utils.check_for_final_answer(
                response, self.repl_env, self.logger,
            )

            if final_answer:
                self.logger.log_final_response(final_answer)
                return final_answer

            
        # If we reach here, no final answer was found in any iteration
        print("No final answer found in any iteration")
        self.messages.append(next_action_prompt(effective_query, iteration, final_answer=True))
        final_answer = self.llm.completion(self.messages)
        self.logger.log_final_response(final_answer)

        return final_answer
    
    def cost_summary(self) -> Dict[str, Any]:
        """Get the cost summary of the Root LM + Sub-RLM Calls."""
        raise NotImplementedError("Cost tracking not implemented for RLM REPL.")

    def reset(self):
        """Reset the (REPL) environment and message history."""
        self.repl_env = REPLEnv()
        self.messages = []
        self.query = None


if __name__ == "__main__":
    pass
