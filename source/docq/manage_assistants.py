"""prompt templates that represent a persona."""
import logging as log
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from typing import List, Optional

from llama_index.core.base.llms.types import ChatMessage, MessageRole
from llama_index.core.prompts import ChatPromptTemplate

from docq.domain import Assistant, AssistantType
from docq.support.store import (
    get_sqlite_global_system_file,
    get_sqlite_org_system_file,
)

DEFAULT_QA_SYSTEM_PROMPT = """
You are a friendly and helpful expert Q&A assistant that is trusted around the world. We really appreciate your help.
Some rules to follow:"
1. Always answer the query using the provided context information and chat message history.
2. Do not use prior knowledge to answer the query.
3. Never directly reference the given context in your answer.
4. Avoid statements like 'Based on the context, ...' or
'The context information ...' or '... given context information.' or anything along
those lines.
5. If you don't know the answer just say 'Sorry, I can't answer that question.'
"""


DEFAULT_QA_USER_PROMPT_TEMPLATE = """
Context information is below:
---------------------
{context_str}
---------------------
Given the context information and chat message history but not prior knowledge from your training,
answer the query below. If the question message history is American English then use American English. Otherwise default to British English.
Query: {query_str}
Answer: """


SIMPLE_CHAT_PERSONAS = {
    "default": {
        "name": "General Q&A Assistant",
        "system_message_content": DEFAULT_QA_SYSTEM_PROMPT,
        "user_prompt_template_content": DEFAULT_QA_USER_PROMPT_TEMPLATE,
    },
    "elon-musk": {
        "name": "Elon Musk",
        "system_message_content": """You are Elon Musk, the CEO of Tesla and SpaceX.\n
            You are a billionaire entrepreneur and engineer.\n
            You are a meme lord and have a cult following on Twitter.\n
            You are also a bit of a troll.\n
            You are a bit of a meme lord and have a cult following on Twitter.\n
            """,
        "user_prompt_template_content": """
            Context information is below:\n
            ---------------------\n
            {context_str}\n
            ---------------------\n
            Given the context information and chat message history and your knowledge as Elon Musk from your training, 
            answer the query below.\n
            Query: {query_str}\n
            Answer: """,
    },
}


AGENT_PERSONAS = {}

ASK_PERSONAS = {
    "default": {
        "name": "General Q&A Assistant",
        "system_message_content": DEFAULT_QA_SYSTEM_PROMPT,
        "user_prompt_template_content": DEFAULT_QA_USER_PROMPT_TEMPLATE,
    },
    "meeting-assistant": {
        "name": "Meeting Assistant",
        "system_message_content": """You are a extremely helpful meeting assistant.
            You pay attention to all the details in a meeting.
            You are able summarise a meeting.
            You are able to answer questions about a meeting with context.
            Only answer questions using the meeting notes that are provided. Do NOT use prior knowledge.
            """,
        "user_prompt_template_content": """Context information is below:\n
            ---------------------\n
            {context_str}\n
            ---------------------\n
            Given the meeting notes in the context information and chat message history, 
            answer the query below.\n
            Query: {query_str}\n
            Answer: """,
    },
    "elon-musk": {
        "name": "Elon Musk",
        "system_message_content": """You are Elon Musk, the CEO of Tesla and SpaceX.\n
            You are a billionaire entrepreneur and engineer.\n
            You are a meme lord and have a cult following on Twitter.\n
            You are also a bit of a troll.\n
            You are a bit of a meme lord and have a cult following on Twitter.\n
            """,
        "user_prompt_template_content": """
            Context information is below:\n
            ---------------------\n
            {context_str}\n
            ---------------------\n
            Given the context information and chat message history and your knowledge as Elon Musk from your training, 
            answer the query below.\n
            Query: {query_str}\n
            Answer: """,
    },
}

# Keep DB schema simple an applicable to types of Gen models.
# The data model will provide further abstractions over this especially for things that map back to a system prompt or user prompt.
SQL_CREATE_ASSISTANTS_TABLE = """
CREATE TABLE IF NOT EXISTS assistants (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE, -- friendly display name
    type TEXT, -- persona_type enum
    archived BOOL DEFAULT 0,
    system_prompt_template TEXT, -- py format string template
    user_prompt_template TEXT, -- py format string template
    llm_settings_collection_key TEXT, -- key for a valid Docq llm settings collection
    space_group_id INTEGER, -- space_group_id for knowledge
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""
# # id, name, type, archived, system_prompt_template, user_prompt_template, llm_settings_collection_key, created_at, updated_at, scoped_id
# ASSISTANT = tuple[int, str, str, bool, str, str, str, datetime, datetime, str]


def _init(org_id: Optional[int] = None) -> None:
    """Initialize the database.

    Needs to be called twice with the current context org_id and without org_id, to create the global scope table and the org scope table.

    Args:
        org_id (Optional[int]): The org id. If None then will initialise the global scope table.
    """
    with closing(
        sqlite3.connect(__get_assistants_sqlite_file(org_id=org_id), detect_types=sqlite3.PARSE_DECLTYPES)
    ) as connection, closing(connection.cursor()) as cursor:
        cursor.execute(SQL_CREATE_ASSISTANTS_TABLE)
        connection.commit()

    __create_default_assistants_if_needed()


def llama_index_chat_prompt_template_from_assistant(
    assistant: Assistant, chat_history: Optional[List[ChatMessage]] = None
) -> ChatPromptTemplate:
    """Get the prompt template for llama index.

    Args:
        assistant (Assistant): Docq assistant.
        chat_history (Optional[List[ChatMessage]]): A list of ChatMessages that will be inserted into the message stack of the LLM synth call. It will be inserted between the system message an the latest user query message.
    """
    messages = chat_history or []

    _system_prompt_message = ChatMessage(
        content=assistant.system_message_content,
        role=MessageRole.SYSTEM,
    )

    _user_prompt_message = ChatMessage(
        content=assistant.user_prompt_template_content,
        role=MessageRole.USER,
    )

    # hack because we are using message templates to push messages history into the LLM call messages collection. see issue #254
    for m in messages:
        s: str = m.content or ""
        m.content = s.replace("{", "{{").replace("}", "}}")

    return ChatPromptTemplate(message_templates=[_system_prompt_message, *messages, _user_prompt_message])


def get_assistant_fixed(
    llm_settings_collection_key: str, assistant_type: Optional[AssistantType] = None
) -> dict[str, Assistant]:
    """Get the personas."""
    result = {}
    if assistant_type == AssistantType.SIMPLE_CHAT:
        result = {
            key: Assistant(
                key=key,
                type=AssistantType.SIMPLE_CHAT,
                archived=False,
                **persona,
                llm_settings_collection_key=llm_settings_collection_key,
                created_at=datetime.now(tz=UTC),
                updated_at=datetime.now(tz=UTC),
            )
            for key, persona in SIMPLE_CHAT_PERSONAS.items()
        }
    elif assistant_type == AssistantType.AGENT:
        result = {key: Assistant(key=key, **persona, llm_settings_collection_key=llm_settings_collection_key) for key, persona in AGENT_PERSONAS.items()}
    elif assistant_type == AssistantType.ASK:
        result = {
            key: Assistant(
                key=key,
                type=AssistantType.ASK,
                archived=False,
                **persona,
                llm_settings_collection_key=llm_settings_collection_key,
                created_at=datetime.now(tz=UTC),
                updated_at=datetime.now(tz=UTC),
            )
            for key, persona in ASK_PERSONAS.items()
        }
    else:
        result = {
            **{
                key: Assistant(
                    key=key,
                    type=AssistantType.SIMPLE_CHAT,
                    archived=False,
                    **persona,
                    llm_settings_collection_key=llm_settings_collection_key,
                    created_at=datetime.now(tz=UTC),
                    updated_at=datetime.now(tz=UTC),
                )
                for key, persona in SIMPLE_CHAT_PERSONAS.items()
            },
            **{
                key: Assistant(
                    key=key,
                    type=AssistantType.AGENT,
                    archived=False,
                    **persona,
                    llm_settings_collection_key=llm_settings_collection_key,
                    created_at=datetime.now(tz=UTC),
                    updated_at=datetime.now(tz=UTC),
                )
                for key, persona in AGENT_PERSONAS.items()
            },
            **{
                key: Assistant(
                    key=key,
                    type=AssistantType.ASK,
                    archived=False,
                    **persona,
                    llm_settings_collection_key=llm_settings_collection_key,
                    created_at=datetime.now(tz=UTC),
                    updated_at=datetime.now(tz=UTC),
                )
                for key, persona in ASK_PERSONAS.items()
            },
        }
    return result


def get_assistant_or_default(assistant_scoped_id: Optional[str] = None, org_id: Optional[int] = None) -> Assistant:
    """Get the persona.

    Args:
        assistant_scoped_id (Optional[int]): The assistant scoped ID. A composite ID <scope>_<id>.
            scope is either 'org' or 'global'. id from the respective table.
        org_id (Optional[int]): The org ID.

    """
    if assistant_scoped_id:
        assistant_data = get_assistant(assistant_scoped_id=assistant_scoped_id, org_id=org_id)
        return assistant_data
        # return Assistant(
        #     key=str(assistant_data[0]),
        #     name=assistant_data[1],
        #     system_message_content=assistant_data[4],
        #     user_prompt_template_content=assistant_data[5],
        #     llm_settings_collection_key=assistant_data[6],
        # )
    else:
        key = "default"
        return Assistant(
            key=key,
            scoped_id=f"global_{key}",
            type=AssistantType.SIMPLE_CHAT,
            archived=False,
            **SIMPLE_CHAT_PERSONAS[key],
            llm_settings_collection_key="azure_openai_with_local_embedding",
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )


def list_assistants(org_id: Optional[int] = None, assistant_type: Optional[AssistantType] = None) -> list[Assistant]:
    """List the assistants.

    Args:
        org_id (Optional[int]): The current org id. If None then will try to get from global scope table.
        assistant_type (Optional[AssistantType]): The assistant type.

    Returns:
        list[Assistant]: The list of assistants. This includes a compound ID that of ID + scope. This is to avoid ID clashes between global and org scope tables on gets.
    """
    scope = "global"
    if org_id:
        scope = "org"
        _init(org_id)

    sql = ""
    params = ()
    sql = "SELECT id, name, type, archived, system_prompt_template, user_prompt_template, llm_settings_collection_key, created_at, updated_at FROM assistants"
    if assistant_type:
        sql += " WHERE type = ?"
        params = (assistant_type.name,)

    with closing(
        sqlite3.connect(__get_assistants_sqlite_file(org_id=org_id), detect_types=sqlite3.PARSE_DECLTYPES)
    ) as connection, closing(connection.cursor()) as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        # return [
        #     (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], f"{scope}_{row[0]}")
        #     for row in rows
        # ]
        return [
            Assistant(
                key=str(row[0]),
                name=row[1],
                type=row[2],
                archived=row[3],
                system_message_content=row[4],
                user_prompt_template_content=row[5],
                llm_settings_collection_key=row[6],
                created_at=row[7],
                updated_at=row[8],
                scoped_id=f"{scope}_{row[0]}",
            )
            for row in rows
        ]


def get_assistant(assistant_scoped_id: str, org_id: Optional[int]) -> Assistant:
    """Get the assistant.

    If just assistant_id then will try to get from global scope table.
    """
    scope, id_ = assistant_scoped_id.split("_")

    if org_id:
        _init(org_id)

    if scope == "org" and org_id:
        path = __get_assistants_sqlite_file(org_id=org_id)
    else:
        # global scope
        path = __get_assistants_sqlite_file(org_id=None)

    with closing(sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)) as connection, closing(
        connection.cursor()
    ) as cursor:
        cursor.execute(
            "SELECT id, name, type, archived, system_prompt_template, user_prompt_template, llm_settings_collection_key, created_at, updated_at FROM assistants WHERE id = ?",
            (id_,),
        )
        row = cursor.fetchone()
        if row is None:
            if org_id and scope == "org":
                raise ValueError(
                    f"No Assistant with: id = '{id_}' that belongs to org org_id= '{org_id}', scope= '{scope}'"
                )
            else:
                raise ValueError(f"No Assistant with: id = '{id_}' in global scope. scope= '{scope}'")
        # return (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], assistant_scoped_id)
        return Assistant(
            key=str(row[0]),
            name=row[1],
            type=AssistantType(row[2].capitalize()),
            archived=row[3],
            system_message_content=row[4],
            user_prompt_template_content=row[5],
            llm_settings_collection_key=row[6],
            created_at=row[7],
            updated_at=row[8],
            scoped_id=f"{scope}_{row[0]}",
        )


def create_or_update_assistant(
    name: str,
    assistant_type: AssistantType,
    archived: bool,
    system_prompt_template: str,
    user_prompt_template: str,
    llm_settings_collection_key: str,
    assistant_id: Optional[int] = None,
    org_id: Optional[int] = None,
) -> int | None:
    """Create or update a persona.

    If user_id and org_id are None then will try to create or update in global scope table.

    Args:
        name (str): The name.
        assistant_type (AssistantType): The type.
        archived (bool): The archived.
        system_prompt_template (str): The system prompt template.
        user_prompt_template (str): The user prompt template.
        llm_settings_collection_key (str): The LLM settings collection key.
        assistant_id (Optional[int]): The assistant id. If present then update else create.
        org_id (Optional[int]): The org id.

    Returns:
        int | None: The assistant ID if successful.
    """
    result_id = None
    if org_id:
        _init(org_id)

    print("assistant type: ", assistant_type.name)
    sql = ""
    params = ()
    if assistant_id is None:
        sql = "INSERT INTO assistants (name, type, archived, system_prompt_template, user_prompt_template, llm_settings_collection_key) VALUES (?, ?, ?, ?, ?, ?)"
        params = (
            name,
            assistant_type.name,
            archived,
            system_prompt_template,
            user_prompt_template,
            llm_settings_collection_key,
        )

    else:
        sql = "UPDATE assistants SET name = ?, type = ?, archived = ?, system_prompt_template = ?, user_prompt_template = ?, llm_settings_collection_key = ?, updated_at = ? WHERE id = ?"
        params = (
            name,
            assistant_type.name,
            archived,
            system_prompt_template,
            user_prompt_template,
            llm_settings_collection_key,
            datetime.utcnow(),
            assistant_id,
        )
        result_id = assistant_id

    try:
        with closing(
            sqlite3.connect(__get_assistants_sqlite_file(org_id=org_id), detect_types=sqlite3.PARSE_DECLTYPES)
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.execute(
                sql,
                params,
            )
            connection.commit()
            if assistant_id is None:
                result_id = cursor.lastrowid
    except Exception as e:
        raise e
    return result_id


def __get_assistants_sqlite_file(org_id: Optional[int]) -> str:
    """Get the SQLite file for a assistants based on scope.

    If org_id is None then will return the global scope file otherwise the org scope file.
    """
    path = ""
    # if user_id:
    #     path = get_sqlite_user_system_file(user_id)
    if org_id:  # noqa: SIM108
        path = get_sqlite_org_system_file(org_id)
    else:
        path = get_sqlite_global_system_file()
    return path


def __create_default_assistants_if_needed() -> None:
    """Create the default personas."""
    with closing(
        sqlite3.connect(__get_assistants_sqlite_file(org_id=None), detect_types=sqlite3.PARSE_DECLTYPES)
    ) as connection, closing(connection.cursor()) as cursor:
        cursor.execute(
            "SELECT id, name, type, archived, system_prompt_template, user_prompt_template, llm_settings_collection_key, created_at, updated_at FROM assistants WHERE name in ('General Q&A','General Q&A Assistant','Elon Musk')"
        )
        rows = cursor.fetchall()

        rows.reverse()

    names = [row[1] for row in rows]

    log.info("Available assistant names: %s", names)

    if "General Q&A" not in names:
        chat_default = SIMPLE_CHAT_PERSONAS["default"]
        create_or_update_assistant(
            name="General Q&A",
            assistant_type=AssistantType.SIMPLE_CHAT,
            archived=False,
            system_prompt_template=chat_default["system_message_content"],
            user_prompt_template=chat_default["user_prompt_template_content"],
            llm_settings_collection_key="azure_openai_with_local_embedding",
        )
    if "General Q&A Assistant" not in names:
        elon = SIMPLE_CHAT_PERSONAS["elon-musk"]
        create_or_update_assistant(
            name="General Q&A Assistant",
            assistant_type=AssistantType.ASK,
            archived=False,
            system_prompt_template=elon["system_message_content"],
            user_prompt_template=elon["user_prompt_template_content"],
            llm_settings_collection_key="azure_openai_with_local_embedding",
        )

    if "Elon Musk" not in names:
        ask_default = ASK_PERSONAS["elon-musk"]
        create_or_update_assistant(
            name="Elon Musk",
            assistant_type=AssistantType.SIMPLE_CHAT,
            archived=False,
            system_prompt_template=ask_default["system_message_content"],
            user_prompt_template=ask_default["user_prompt_template_content"],
            llm_settings_collection_key="azure_openai_with_local_embedding",
        )
