"""Research helpers — multi-provider search fan-out + deep research tasks."""



from veridiq.research.deep_research import (

    deep_research,

    extract_research_query,

    format_research_answer,

    looks_like_research_task,

)

from veridiq.research.multi_search import configured_providers, multi_search



__all__ = [

    "configured_providers",

    "multi_search",

    "deep_research",

    "looks_like_research_task",

    "extract_research_query",

    "format_research_answer",

]


