import datetime
import io
import csv
import anthropic
import logging
import streamlit as st
import psycopg2
from app.chatlog.chatlog_handler import insert_chat_log, initialize_chatlog_table
from sidebar import setup_sidebar
from app.db.database_connection import get_app_description, get_app_title, initialize_db, update_app_description
from app.instructions.instructions_handler import get_latest_instructions
import uuid

# Streamlit page configuration
st.set_page_config(page_title="Teaching & Learning Chatbot", page_icon=":books:", layout="wide")

# Initialize app title and description
app_title = get_app_title()
app_description = get_app_description() or "Chatbot to support teaching and learning"
st.title(app_title)
st.markdown(app_description, unsafe_allow_html=True)

# Session state management
if "is_admin" not in st.session_state:
    st.session_state["is_admin"] = False
if "conversation_id" not in st.session_state:
    st.session_state["conversation_id"] = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

# Sidebar setup
setup_sidebar()

# Fetch API key and Neon DB link from secrets
anthropic_api_key = st.secrets.get("ANTHROPIC_API_KEY", None)
neon_db_link = st.secrets.get("NEON_DB_LINK", None)

# Neon DB Connection
conn = None
if neon_db_link:
    try:
        conn = psycopg2.connect(neon_db_link)
        st.success("Connected to Neon DB successfully!")
    except Exception as e:
        st.error("Failed to connect to Neon DB. Please check your connection string in secrets.")
        logging.error(f"Neon DB connection error: {e}")
else:
    st.error("Neon DB connection link is missing in secrets!")

# Initialize database and chatlog
initialize_db()
initialize_chatlog_table()

# Anthropics Claude 3.5 Sonnet Client
claude_client = None
if anthropic_api_key:
    try:
        claude_client = anthropic.Client(api_key=anthropic_api_key)
        st.success("Anthropic API initialized successfully!")
    except Exception as e:
        st.error("Failed to initialize Anthropics API. Please check your API key in secrets.")
        logging.error(f"Anthropic API initialization error: {e}")
else:
    st.error("Anthropic API key is missing in secrets!")

# Chat UI
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("What would you like to ask?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate assistant response with Claude
    if claude_client:
        conversation_context = [{"role": "system", "content": get_latest_instructions()}]
        conversation_context += [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""
            try:
                response = claude_client.completions.create(
                    model="claude-3.5-sonnet",
                    messages=conversation_context,
                    max_tokens_to_sample=500,
                    stop_sequences=["\n\n"],
                    stream=True,
                )
                for chunk in response:
                    if "completion" in chunk:
                        full_response += chunk["completion"]
                        message_placeholder.markdown(full_response + "▌")
                    else:
                        logging.warning(f"Unexpected chunk format: {chunk}")
            except Exception as e:  # Catch all exceptions
                st.error("An error occurred while processing your request.")
                logging.error(f"Error: {e}")
            finally:
                message_placeholder.markdown(full_response)
                if full_response:
                    insert_chat_log(prompt, full_response, st.session_state["conversation_id"])
                    st.session_state.messages.append({"role": "assistant", "content": full_response})


        # Provide resources based on user query
        def provide_resources(topic):
            resources = {
                "Python": ["Python Official Docs: https://docs.python.org", "W3Schools Python Tutorial: https://www.w3schools.com/python/"],
                "Machine Learning": ["ML Crash Course by Google: https://developers.google.com/machine-learning/crash-course", "Scikit-learn User Guide: https://scikit-learn.org/stable/user_guide.html"],
                "Web Development": ["MDN Web Docs: https://developer.mozilla.org", "FreeCodeCamp: https://www.freecodecamp.org/"],
            }
            return resources.get(topic, ["Explore more at: https://www.google.com"])

        # Detect topic and suggest resources
        topic = "General"  # Replace with NLP-based topic detection logic if needed
        if "python" in prompt.lower():
            topic = "Python"
        elif "machine learning" in prompt.lower():
            topic = "Machine Learning"
        elif "web" in prompt.lower():
            topic = "Web Development"

        related_resources = provide_resources(topic)
        st.markdown("\n\n**Related Resources:**\n" + "\n".join(related_resources))
    else:
        st.error("Claude API is not initialized. Please check your API key.")

# Admin actions
if st.session_state["is_admin"]:
    st.sidebar.header("Admin Settings")
    new_title = st.text_input("Edit App Title", value=app_title)
    new_description = st.text_area("Edit App Description", value=app_description)
    if st.button("Save Changes"):
        update_app_description(new_title, new_description)
        st.success("Application details updated successfully!")

# Save conversation option
if st.button("Download Conversation"):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Role", "Message"])
    for msg in st.session_state.messages:
        writer.writerow([msg["role"], msg["content"]])
    st.download_button(
        "Download Chat Log",
        output.getvalue(),
        file_name="chat_log.csv",
        mime="text/csv",
    )
