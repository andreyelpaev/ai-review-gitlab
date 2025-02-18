import os
import json
import requests
from flask import Flask, request
import openai

app = Flask(__name__)

openai.api_key = os.environ.get("OPENAI_API_KEY")
gitlab_token = os.environ.get("GITLAB_TOKEN")
gitlab_url = os.environ.get("GITLAB_URL")

api_base = os.environ.get("AZURE_OPENAI_API_BASE")
if api_base != None:
    openai.api_base = api_base

openai.api_version = os.environ.get("AZURE_OPENAI_API_VERSION")
if openai.api_version != None:
    openai.api_type = "azure"

client = openai.OpenAI(
    base_url=os.environ.get("OPENAI_API_BASE"),
    api_key=os.environ.get("OPENAI_API_KEY"),  # This is the default and can be omitted
)

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get("X-Gitlab-Token") != os.environ.get("EXPECTED_GITLAB_TOKEN"):
        return "Unauthorized", 403
    payload = request.json
    if payload.get("object_kind") == "merge_request":
        if payload["object_attributes"]["action"] != "open":
            return "Not a  PR open", 200
        project_id = payload["project"]["id"]
        mr_id = payload["object_attributes"]["iid"]
        changes_url = f"{gitlab_url}/projects/{project_id}/merge_requests/{mr_id}/changes"

        headers = {"Private-Token": gitlab_token}
        response = requests.get(changes_url, headers=headers)
        mr_changes = response.json()

        diffs = [change["diff"] for change in mr_changes["changes"]]

        pre_prompt = "Review the following git diff code changes, focusing on structure, security, and clarity. Provide code suggestions for best practices alignment."

        questions = """
        Questions:
        1. Summarize key changes.
        2. Is the new/modified code clear?
        3. Are comments and names descriptive?
        4. Can complexity be reduced? Examples?
        5. Any bugs? Where?
        6. Potential security issues?
        7. Suggestions for best practices alignment?
        """

        messages = [
            {"role": "system", "content": "You are a senior developer reviewing code changes. You always answer in Russian."},
            {"role": "user", "content": f"{pre_prompt}\n\n{''.join(diffs)}{questions}"},
            {"role": "assistant", "content": "Respond in GitLab-friendly markdown. Include a concise version of each question in your response. You always answer in Russian."},
        ]

        try:
            completions = client.chat.completions.create(
                model=os.environ.get("OPENAI_API_MODEL") or "gpt-3.5-turbo",
                stream=False,
                messages=messages
            )
            answer = completions.choices[0].message.content
            answer += "\n\n"
        except Exception as e:
            print(e)
            answer = "I'm sorry, I'm not feeling well today. Please ask a human to review this PR."
            answer += "\n\n"
            answer += "\n\nError: " + str(e)

        print(answer)
        comment_url = f"{gitlab_url}/projects/{project_id}/merge_requests/{mr_id}/notes"
        comment_payload = {"body": answer}
        comment_response = requests.post(comment_url, headers=headers, json=comment_payload)
    elif payload.get("object_kind") == "push":
        project_id = payload["project_id"]
        commit_id = payload["after"]
        commit_url = f"{gitlab_url}/projects/{project_id}/repository/commits/{commit_id}/diff"

        headers = {"Private-Token": gitlab_token}
        response = requests.get(commit_url, headers=headers)
        changes = response.json()

        changes_string = ''.join([str(change) for change in changes])

        pre_prompt = "Review the git diff of a recent commit, focusing on clarity, structure, and security."

        questions = """
        Questions:
        1. Summarize changes (Changelog style).
        2. Clarity of added/modified code?
        3. Comments and naming adequacy?
        4. Simplification without breaking functionality? Examples?
        5. Any bugs? Where?
        6. Potential security issues?
        """

        messages = [
            {"role": "system", "content": "You are a senior developer reviewing code changes from a commit. You always answer in Russian."},
            {"role": "user", "content": f"{pre_prompt}\n\n{changes_string}{questions}"},
            {"role": "assistant", "content": "Respond in markdown for GitLab. Include concise versions of questions in the response. You always answer in Russian."},
        ]

        print(messages)
        try:
            completions = client.chat.completions.create(
                model=os.environ.get("OPENAI_API_MODEL") or "gpt-3.5-turbo",
                stream=False,
                messages=messages
            )
            answer = completions.choices[0].message["content"].strip()
            answer += "\n\nFor reference, i was given the following questions: \n"
            for question in questions.split("\n"):
                answer += f"\n{question}"
            answer += "\n\n"
        except Exception as e:
            print(e)
            answer = "I'm sorry, I'm not feeling well today. Please ask a human to review this code change."
            answer += "\n\n"
            answer += "\n\nError: " + str(e)

        print(answer)
        comment_url = f"{gitlab_url}/projects/{project_id}/repository/commits/{commit_id}/comments"
        comment_payload = {"note": answer}
        comment_response = requests.post(comment_url, headers=headers, json=comment_payload)

    return "OK", 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
