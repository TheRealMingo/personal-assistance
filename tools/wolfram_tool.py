import datetime
from langchain.tools import tool
import tools.tool_usage_utils as tuu
import pytz
import googlemaps
from config.config import config
import requests
from urllib.parse import quote_plus

import logging
logging.basicConfig(filename='personal_assistant_tool.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
from tools.api_call_tracker import record_api_call


@tool(return_direct=True)
def wolfram_tool(query: str) -> str:
    """Use wolfram to answer a science, technology, engineering, and math question.
    Wolfram can solve a wide range of science, technology, engineering, and math related questions.  
    
    Args:
        query: The query to answer. The query should be a short, declarative statement of the question to answer. 
        For example, if the user asks "What is the derivative of x^2?" the query should be "derivative of x^2". If the user asks "What is the integral of x^2?" the query should be "integral of x^2". If the user asks "What is the solution to x^2 + 2x + 1 = 0?" the query should be "solution to x^2 + 2x + 1 = 0". Always rephrase the user's question into a short, declarative statement that can be used as a query for Wolfram Alpha.
    """
    logging.info(f"Query to Wolfram Alpha: {query}")
    tuu.tool_usage_counter["wolfram_tool"] = tuu.tool_usage_counter["wolfram_tool"] + 1
    record_api_call("wolfram_alpha")
    query = quote_plus(query)
    # Documentation of the LLM API: https://products.wolframalpha.com/llm-api/documentation
    api_call = f"http://api.wolframalpha.com/v1/llm-api?input={query}&appid={config['wolfram_alpha_llm_api_key']}"
    logged_url = f"http://api.wolframalpha.com/v1/llm-api?input={query}&appid=REDACTED"
    logging.info(f"Making API call to Wolfram Alpha: {logged_url}")
    response = requests.get(api_call)
    logging.info(f"Wolfram Alpha API status: {response.status_code}")
    if response.status_code == 200:
        logging.info(f"Wolfram Alpha response: {response.text}")
        return response.text
    else:
        logging.error(f"Error calling Wolfram Alpha API: {response.status_code} - {response.text}")
        return f"Could not retrieve information for the query {query}."