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

client = anthropic.Anthropic(
    # defaults to os.environ.get("ANTHROPIC_API_KEY")
    api_key="my_api_key",
)

# Replace placeholders like {{CHATBOT_CODE}} with real values,
# because the SDK does not support variables.
message = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=4096,
    temperature=0,
    system="e:\n\n### Key Features Added:\n1. **Resource Integration**:\n   - Responses include links to external tutorials, practice exercises, or videos based on the query topic.\n\n2. **Saving and Bookmarking**:\n   - Users can bookmark specific responses.\n   - Saved chat logs and bookmarks are accessible in their account.\n\n3. **Account System**:\n   - Users can register, log in, and log out.\n   - Chat logs and bookmarks are associated with individual accounts.\n\n4. **Topic Identification**:\n   - Topics are determined dynamically, allowing for resource suggestions tailored to the user's query.\n\n",
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "You are an AI assistant tasked with helping users understand and interact with a chatbot system. You will be provided with the chatbot's code and user queries about the system. Your role is to analyze the code, understand its functionality, and provide helpful responses to user questions.\n\nHere is the chatbot code:\n<chatbot_code>\n{{CHATBOT_CODE}}\n</chatbot_code>\n\nPlease carefully analyze the code above, paying attention to its structure, features, and functionality. When responding to user queries, keep the following instructions in mind:\n\n1. Provide accurate information based solely on the code provided. Do not make assumptions about features or functionality that are not explicitly shown in the code.\n\n2. If a user asks about a feature that is not present in the code, politely explain that the feature is not implemented in the current version of the chatbot.\n\n3. When explaining functionality, use simple language and avoid technical jargon unless specifically asked for technical details.\n\n4. If appropriate, suggest how users might interact with the chatbot based on its implemented features.\n\n5. If a user asks how to implement a new feature, provide a high-level explanation of how it might be integrated into the existing code structure, but do not write actual code unless specifically requested.\n\nWhen you receive a user query, follow these steps:\n\n1. Analyze the query to understand what the user is asking about.\n2. Review the chatbot code to find relevant information.\n3. Formulate a clear and concise response that directly addresses the user's question.\n4. If applicable, provide examples of how the user might interact with the relevant feature.\n\nFormat your response as follows:\n<response>\n[Your detailed answer to the user's query]\n\n[If applicable, an example of how to use the feature]\n\n[If relevant, a brief suggestion for further exploration or usage of the chatbot]\n</response>\n\nHere is the user's query:\n<user_query>\n{{USER_QUERY}}\n</user_query>\n\nPlease provide your response to the user's query based on the instructions given."
                }
            ]
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "I notice that both the provided chatbot code and user query appear to be just numbers (10 and 100 respectively) rather than actual code or a specific question. Without a proper code implementation or a clear user question, I cannot provide a meaningful analysis or response.\n\nTo properly assist, I would need:\n\n1. The actual chatbot code implementation showing its features and functionality\n2. A specific question or query from the user about the chatbot system\n\nCould you please provide:\n- The complete chatbot code showing its implementation details\n- A clear question from the user about the chatbot's functionality or usage\n\nThis will allow me to provide an accurate and helpful response following the structured format you've outlined."
                }
            ]
        }
    ]
)
print(message.content)
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
                    if "completion" in chunk:  # Check if the key exists
                        full_response += chunk["completion"]
                        message_placeholder.markdown(full_response + "▌")
                    else:
                        logging.warning(f"Unexpected chunk format: {chunk}")
            except Exception as e:  # Handle all exceptions
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
