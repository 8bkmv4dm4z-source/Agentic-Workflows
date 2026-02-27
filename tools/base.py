from typing import Dict, Any

class Tool:
    name:str
    description:str

    def execute(self,args:Dict[str,Any])->Dict[str, Any]:
        raise NotImplementedError("Tool must implement the execute method.")