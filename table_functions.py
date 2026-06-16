from langchain.chains import RetrievalQA,RetrievalQAWithSourcesChain
from langchain import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
import langchain
from langchain import SQLDatabase
from langchain_experimental.sql import SQLDatabaseChain
from langchain.chains.sql_database.prompt import PROMPT, SQL_PROMPTS
from langchain import LLMChain

import pandas as pd
import ast
import textwrap
import os
import time
from argparse import ArgumentParser
import sys
import glob
import json
import re


import os
import time
from argparse import ArgumentParser
import sys
import json
import math
import requests
from func_timeout import func_set_timeout
import func_timeout


import sqlite3

langchain.verbose = False

TABLE_PARAMETER = "{TABLE_PARAMETER}"
c_tr_index = "{c_tr_index}"
DROP_TABLE_SQL = f"DROP TABLE {TABLE_PARAMETER};"
GET_TABLES_SQL = "SELECT name FROM sqlite_schema WHERE type='table';"
GET_ROW_SQL = f"""SELECT * FROM {TABLE_PARAMETER} WHERE "index" = {c_tr_index};"""
def delete_all_tables(con):
    tables = get_tables(con)
    delete_tables(con, tables)

def get_row(con, c_table, c_index):
    cur = con.cursor()
    sql = GET_ROW_SQL.replace(TABLE_PARAMETER, c_table); sql = sql.replace(c_tr_index, str(c_index))
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    return rows


def get_tables(con):
    cur = con.cursor()
    cur.execute(GET_TABLES_SQL)
    tables = cur.fetchall()
    cur.close()
    return tables


def delete_tables(con, tables):
    cur = con.cursor()
    for table, in tables:
        sql = DROP_TABLE_SQL.replace(TABLE_PARAMETER, table)
        cur.execute(sql)
    cur.close()

@func_set_timeout(40)
def table2text(llm, tableRow, question):
    llm_chain = LLMChain(
    llm=llm,
    prompt=PromptTemplate.from_template(template_PM3_table2text)
    )

    result = llm_chain.generate([{"tableData":tableRow, "question":question}])
    return result.generations[0][0].text


@func_set_timeout(40)
def tableNtext_qa(llm, tableRow, pt, question):
    llm_chain = LLMChain(
    llm=llm,
    prompt=PromptTemplate.from_template(template_PM3_tableNtext_qa)
    )

    result = llm_chain.generate([{"tableData":tableRow, "pt":pt, "question":question}])
    return result.generations[0][0].text

@func_set_timeout(40)
def wrapper(func, query):
    return(func(query))



def is_number(s):
    try: 
        float(s)
        return True
    except ValueError:
        pass

    return False


# for benchmarking only, generate half-sturctured data in plain text from single table_row
template_PM3_table2text = """
### System:
You are reading the structured data given in the Context and try to rephrase it in plain text. In each line, the attribute name(header) is on the left of *:*, then corresponding attribute value is on the right.

### Context:
{tableData}

### User:
Each variant/mutation must contain alphabet letters with several digits, don't make up non-existed variants/mutations. 
Limit your answer under 25 words.
Stop the answer by the word *END*.
Please read the above provided structured data in context and just answer the given question in short plain text. Question: {question}'\
### Response:

"""




template_PM3_tableNtext_qa = """
### System:
You are reading the structured data and it's corresponding plain text description given in the Context, try to answer user's question based on these. For structured data, in each line, the attribute name(header) is on the left of *:*, then corresponding attribute value is on the right.

### Context:
structured data {tableData}

plain text description {pt}

### User:
Limit your answer under 100 words and don't repeat the context or any info you are given. Please read the above provided structured data and it's corresponding plain text description in context and just answer the given question. Question: {question}'\
### Response:

"""



def table_extraction_with_deepseek(current_paper_tables, query_variant_list, model_name="deepseek-v4-flash", api_key=None, api_url=None):
    """
    使用 DeepSeek 模型直接从 CSV 表格内容中查找 variant
    替代原来的 sqlcoder + SQLDatabaseChain 方式

    Args:
        current_paper_tables: list of DataFrame 或 CSV 文件路径列表
        query_variant_list: variant 列表，如 ['1319', '440', 'c.1319T>G']
        model_name: DeepSeek 模型名
        api_key: DeepSeek API key
        api_url: OpenAI-compatible API URL (optional)

    Returns:
        [answers_list, variant_found] - 与原接口兼容
    """
    if api_url:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=model_name, api_key=api_key, base_url=api_url, temperature=0.0, top_p=0.9)
    else:
        from langchain_deepseek import ChatDeepSeek
        llm = ChatDeepSeek(model=model_name, api_key=api_key, temperature=0.0, top_p=0.9)

    df_list = []
    for c_table in current_paper_tables:
        try:
            if isinstance(c_table, pd.DataFrame):
                df_list.append(c_table)
            else:
                df_list.append(pd.read_csv(c_table, header=None))
        except Exception as e:
            print(f"current table is invalid: {c_table}")

    # 打印所有提取到的表格
    print(f"\n========== Extracted {len(df_list)} tables ==========")
    for idx, df in enumerate(df_list):
        print(f"\n--- Table {idx + 1} (shape: {df.shape}) ---")
        print(df.to_string())
    print("=" * 50)

    # 不再过滤，直接把所有表格交给模型判断
    basic_query_answers_list = []

    for idx, df in enumerate(df_list):
        csv_content = df.to_csv(index=False)

        query_text = " ".join(str(v) for v in query_variant_list)
        prompt = f"""You are a scientific research assistant. Given this table from a biomedical paper:

--- Table {idx + 1} ---
{csv_content}
---

Question: Look for any variant mentioned in this table related to: {query_text}
- Extract all rows that contain these variants
- Identify which column contains the variant information (usually POMGnT1 or similar gene columns)
- Summarize what the table shows about these variants

If no variants are found, respond with: "No variant match in this table"

Answer:"""

        try:
            response = llm.invoke(prompt)
            answer_text = response.content if hasattr(response, 'content') else str(response)

            # 兼容原接口格式
            basic_query_answers_list.append((f"table_{idx}", [{"plainText": answer_text}]))
        except Exception as e:
            print(f"Error querying table {idx}: {e}")
            basic_query_answers_list.append([(f"table_{idx}", [{"plainText": f"Error: {e}"}])])

    return [basic_query_answers_list, True]  # True = 告诉调用方有表格内容

