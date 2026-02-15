#!/usr/bin/env python3
"""
Generate realistic test transcripts for testing Modal RLM pipeline.
Follows the example-transcripts format with metadata headers.
"""

import random
import uuid
from datetime import datetime, timedelta
import argparse


def generate_session_id():
    """Generate a realistic session ID"""
    return str(uuid.uuid4())


def generate_timestamp(base_time, offset_seconds=0):
    """Generate ISO timestamp"""
    return (base_time + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def create_metadata(session_id, message_count, start_time, end_time):
    """Create session metadata header"""
    return f"""========================================================================
SESSION METADATA
========================================================================
session_id:      {session_id}
developer:       testuser
email:           test@example.com
hostname:        test-machine.local
platform:        Darwin
os_user:         testuser
git_branch:      main
project_dir:     /Users/test/project
claude_version:  2.1.42
message_count:   {message_count}
start_time:      {start_time}
end_time:        {end_time}
uploaded_at:     {datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"}
========================================================================

"""


# Conversation templates for different scenarios
CONVERSATION_TEMPLATES = {
    "deployment": [
        ("USER", "We need to deploy the new authentication service. What's our deployment strategy?"),
        ("ASSISTANT", "Let's use a blue-green deployment. We'll spin up the new version alongside the old one, test it, then switch traffic over. This minimizes downtime and gives us an easy rollback path."),
        ("USER", "What about the database migrations?"),
        ("ASSISTANT", "We should run migrations in a backwards-compatible way first. Add new columns without making them required, deploy the code, then in a follow-up deployment enforce constraints. That way rollback is safe."),
        ("USER", "When should we schedule this?"),
        ("ASSISTANT", "Best window is Tuesday 2 AM PST when traffic is lowest. The deployment should take about 30 minutes including verification. I'll set up monitoring dashboards to track error rates during the transition."),
        ("USER", "Who owns the rollback decision?"),
        ("ASSISTANT", "The on-call engineer (Sarah) has rollback authority if error rates spike above 1% or latency exceeds 500ms for more than 2 minutes. I'll document the rollback procedure in the runbook."),
    ],

    "debugging": [
        ("USER", "Users are reporting intermittent 500 errors on the checkout page."),
        ("ASSISTANT", "Let me check the logs. Looking at the error traces, I see sporadic Redis connection timeouts. The pattern suggests we're hitting connection pool exhaustion during traffic spikes."),
        ("USER", "What's causing the pool exhaustion?"),
        ("ASSISTANT", "The payment service is not releasing Redis connections properly after failed transactions. Each retry leaks a connection. After analyzing 100 failed requests, 87% show this pattern."),
        ("USER", "How do we fix it?"),
        ("ASSISTANT", "Two-part fix: 1) Wrap Redis calls in try-finally blocks to ensure connection release, 2) Increase the connection pool size from 10 to 50 as a short-term buffer. I'll also add alerting when pool utilization exceeds 80%."),
        ("USER", "What's the root cause?"),
        ("ASSISTANT", "The issue was introduced in commit abc123f when we added retry logic but didn't handle the connection cleanup in the error path. The code review missed it because the tests only covered the happy path."),
    ],

    "architecture": [
        ("USER", "We're redesigning the notification system. Current system sends 10M emails/day and is struggling."),
        ("ASSISTANT", "The bottleneck is the synchronous SMTP calls blocking web workers. We should move to an async architecture: web tier writes to a message queue (SQS/Kafka), dedicated worker fleet consumes and sends emails."),
        ("USER", "How do we handle failures and retries?"),
        ("ASSISTANT", "Use exponential backoff with jitter. Failed messages go to a dead letter queue after 5 attempts. We'll need a dashboard to monitor the DLQ and a runbook for manual intervention when providers have outages."),
        ("USER", "What about scaling?"),
        ("ASSISTANT", "Workers can autoscale based on queue depth. Target: keep queue depth under 1000 messages. At 10M emails/day that's ~115 emails/second, so we'd need 12-15 workers assuming 10 emails/second/worker throughput."),
        ("USER", "Cost implications?"),
        ("ASSISTANT", "Current setup: 5 large web servers = $800/month. New setup: 3 medium web servers + 15 small workers + SQS = $650/month. Plus we gain horizontal scalability and better failure isolation."),
    ],

    "data_analysis": [
        ("USER", "Analyze user retention for the new onboarding flow vs the old one."),
        ("ASSISTANT", "Looking at 10,000 users on each flow over 30 days. New flow: 45% retention at day 30. Old flow: 32% retention. That's a 40% relative improvement, statistically significant (p < 0.01)."),
        ("USER", "What's driving the improvement?"),
        ("ASSISTANT", "Breaking it down by cohort: the biggest gains are in the 'power user' segment (users who created 5+ items in week 1). New onboarding gets 28% to that milestone vs 19% in old flow. Once users hit that milestone, retention is similar (78% vs 75%)."),
        ("USER", "Which specific onboarding steps matter most?"),
        ("ASSISTANT", "The interactive tutorial added in step 2 has the highest correlation with power user conversion (0.67 correlation coefficient). Users who complete it are 3.2x more likely to hit the 5-item milestone."),
        ("USER", "What's the business impact?"),
        ("ASSISTANT", "At current signup rate of 1000 users/week, the improved retention means 130 additional retained users per week. With average LTV of $500, that's $65K additional annual revenue. ROI on the onboarding redesign hits breakeven in 2.3 months."),
    ],
}


def generate_conversation(template_type, num_exchanges=None):
    """Generate a conversation from a template"""
    if template_type == "mixed":
        # Mix different conversation types
        all_exchanges = []
        for template in CONVERSATION_TEMPLATES.values():
            all_exchanges.extend(template)
        random.shuffle(all_exchanges)
        if num_exchanges:
            all_exchanges = all_exchanges[:num_exchanges]
        return all_exchanges
    else:
        exchanges = CONVERSATION_TEMPLATES.get(template_type, [])
        if num_exchanges:
            # Repeat and extend if needed
            while len(exchanges) < num_exchanges:
                exchanges.extend(CONVERSATION_TEMPLATES[template_type])
            exchanges = exchanges[:num_exchanges]
        return exchanges


def format_transcript(session_id, conversation, start_time):
    """Format conversation as transcript"""
    current_time = start_time
    messages = []

    for i, (role, content) in enumerate(conversation):
        timestamp = generate_timestamp(current_time, i * 30)  # 30 seconds between messages
        messages.append(f"[{role}] [{timestamp}]\n{content}\n\n---\n")

    end_time = generate_timestamp(current_time, len(conversation) * 30)

    metadata = create_metadata(
        session_id=session_id,
        message_count=len(conversation),
        start_time=generate_timestamp(current_time, 0),
        end_time=end_time
    )

    return metadata + "\n".join(messages)


def main():
    parser = argparse.ArgumentParser(description="Generate test transcripts for Modal RLM pipeline")
    parser.add_argument("--type", choices=["deployment", "debugging", "architecture", "data_analysis", "mixed"],
                        default="mixed", help="Type of conversation to generate")
    parser.add_argument("--exchanges", type=int, default=20,
                        help="Number of message exchanges (USER + ASSISTANT pairs)")
    parser.add_argument("--output", default="test_modal_transcript.txt",
                        help="Output file path")

    args = parser.parse_args()

    # Generate conversation
    session_id = generate_session_id()
    start_time = datetime.utcnow() - timedelta(hours=2)

    conversation = generate_conversation(args.type, args.exchanges)
    transcript = format_transcript(session_id, conversation, start_time)

    # Write to file
    with open(args.output, "w") as f:
        f.write(transcript)

    print(f"✅ Generated transcript: {args.output}")
    print(f"   Session ID: {session_id}")
    print(f"   Messages: {len(conversation)}")
    print(f"   Size: {len(transcript)} chars")


if __name__ == "__main__":
    main()
