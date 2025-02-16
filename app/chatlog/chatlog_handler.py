import csv
import io
import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import psycopg2
import anthropic

# Configure logging to output INFO level messages.
logging.basicConfig(level=logging.INFO)

# Establish a connection to the database using Streamlit Secrets
def connect_to_db():
    neon_db_link = st.secrets.get("NEON_DB_LINK")
    if not neon_db_link:
        logging.error("NEON_DB_LINK not found in Streamlit secrets.")
        return None
    try:
        conn = psycopg2.connect(neon_db_link)
        return conn
    except Exception as e:
        logging.error(f"Failed to connect to the database: {e}")
        return None

# Insert a chat log into the database
def insert_chat_log(prompt, response, conversation_id):
    conn = connect_to_db()
    if conn is None:
        logging.error("Failed to connect to the database.")
        return
    # If no conversation_id is provided, create a new one.
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    # Get current time in GMT+8 (Asia/Singapore)
    now_in_sgt = datetime.now(ZoneInfo("Asia/Singapore"))
    try:
        # Validate and standardize the conversation_id as a UUID string.
        conversation_uuid = str(uuid.UUID(conversation_id))
    except Exception as e:
        logging.error(f"Invalid conversation_id format '{conversation_id}': {e}")
        conversation_uuid = str(uuid.uuid4())
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_logs (prompt, response, timestamp, conversation_id)
                VALUES (%s, %s, %s, %s)
                """,
                (prompt, response, now_in_sgt, conversation_uuid)
            )
            conn.commit()
            logging.info("Chat log inserted successfully.")
    except Exception as e:
        logging.error(f"Error inserting chat log: {e}")
    finally:
        if conn:
            conn.close()

# Initialize the chat logs table
def initialize_chatlog_table():
    conn = connect_to_db()
    if conn is None:
        logging.error("Failed to connect to the database.")
        return

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_logs (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT current_timestamp,
                    prompt TEXT,
                    response TEXT,
                    conversation_id UUID
                );
                """
            )
            conn.commit()
            logging.info("Chatlog table (re)created successfully.")
    except Exception as e:
        logging.error(f"Error (re)creating chatlog table: {e}")
    finally:
        if conn:
            conn.close()

# Fetch all chat logs from the database
def fetch_chat_logs():
    conn = connect_to_db()
    if conn is None:
        logging.error("Failed to connect to the database for fetching logs.")
        return []
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM chat_logs")
            chat_logs = cur.fetchall()
            logging.info(f"Fetched {len(chat_logs)} chat log records.")
            return chat_logs
    except Exception as e:
        logging.error(f"Error fetching chat logs: {e}")
        return []
    finally:
        if conn:
            conn.close()

# Batch chat logs by conversation ID
def fetch_and_batch_chatlogs():
    conn = connect_to_db()
    if conn is None:
        logging.error("Failed to connect to the database for fetching logs.")
        return {}

    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT conversation_id, prompt, response FROM chat_logs")
            chat_logs = cur.fetchall()
            batches = {}
            for log in chat_logs:
                # Rename the variable to avoid shadowing the uuid module.
                conv_id = str(log[0])
                if conv_id not in batches:
                    batches[conv_id] = []
                # Combine prompt and response (you might add a separator if desired)
                batches[conv_id].append(log[1] + " " + log[2])
            return batches
    except Exception as e:
        logging.error(f"Error fetching and batching chat logs: {e}")
        return {}
    finally:
        if conn:
            conn.close()

# Export chat logs to CSV
def export_chat_logs_to_csv(filename='chat_logs.csv'):
    chat_logs = fetch_chat_logs()
    if not chat_logs:
        logging.info("No chat logs to export.")
        return
    # Create a CSV in memory with UTF-8 encoding
    output = io.StringIO()
    writer = csv.writer(output)
    # Write headers matching the database columns.
    writer.writerow(['ID', 'Timestamp', 'Prompt', 'Response', 'ConversationID'])
    for log in chat_logs:
        writer.writerow(log)
    return output.getvalue().encode('utf-8-sig')

# Delete all chat logs
def delete_all_chatlogs():
    conn = connect_to_db()
    if conn is None:
        logging.error("Failed to connect to the database.")
        return
    try:
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM chat_logs")
            conn.commit()
            logging.info("All chat logs deleted successfully.")
    except Exception as e:
        logging.error(f"Error deleting chat logs: {e}")
    finally:
        if conn:
            conn.close()

# Drop the chat logs table
def drop_chatlog_table():
    conn = connect_to_db()
    if conn is None:
        logging.error("Failed to connect to the database.")
        return
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS chat_logs;")
            conn.commit()
            logging.info("Chatlog table dropped successfully.")
    except Exception as e:
        logging.error(f"Error dropping chatlog table: {e}")
    finally:
        if conn:
            conn.close()

# Generate summaries for chat logs using Anthropics API
def generate_summary_for_each_group(batches):
    summaries = {}
    anthropic_api_key = st.secrets.get("ANTHROPIC_API_KEY")
    if not anthropic_api_key:
        logging.error("Anthropic API key is missing in secrets.")
        return summaries

    client = anthropic.Client(api_key=anthropic_api_key)
    for idx, (conv_id, logs) in enumerate(batches.items(), start=1):
        combined_logs = "\n".join(logs)
        messages = [
            {"role": "system", "content": "Summarize the following conversation."},
            {"role": "user", "content": combined_logs}
        ]
        try:
            response = client.completions.create(
                model="claude-3.5-sonnet",
                messages=messages,
                max_tokens_to_sample=300
            )
            summaries[conv_id] = response["completion"].strip()
        except Exception as e:
            summaries[conv_id] = f"Failed to generate summary: {e}"
    return summaries

# Compile summaries into a structured output string
def compile_summaries(summaries):
    compiled_output = "Top-level summary:\n"
    for idx, (conv_id, summary) in enumerate(summaries.items(), start=1):
        compiled_output += f"\nGroup {idx} summary (UUID {conv_id}):\n{summary}\n"
    return compiled_output

# Fetch, summarize, and compile chat logs
if __name__ == "__main__":
    batches = fetch_and_batch_chatlogs()
    group_summaries = generate_summary_for_each_group(batches)
    final_summary_output = compile_summaries(group_summaries)
    # For demonstration, print the final summary output
    print(final_summary_output)
