from __future__ import annotations
import logging
import os
import asyncio
from dotenv import load_dotenv

from openai import AsyncAzureOpenAI
from agents import Agent, HandoffInputData, Runner, function_tool, handoff, trace, set_default_openai_client, OpenAIChatCompletionsModel, add_trace_processor
from agents.tracing.processors import ConsoleSpanExporter, BatchTraceProcessor
from agents.extensions import handoff_filters
import logfire



load_dotenv()

azure_openai_client = AsyncAzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY2"),
    api_version=os.getenv("AZURE_OPENAI_VERSION2"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT2"),
    azure_deployment=os.getenv("AZURE_DEPLOYMENT2")
)



openai_client = azure_openai_client
set_default_openai_client(openai_client)



# Configure logfire
logfire.configure(
    service_name='banking-agent-service',
    send_to_logfire=False,
)
logfire.instrument_openai_agents()

@function_tool
def check_account_balance(account_id: str) -> float:
    """Check the balance of a bank account."""
    # This is a mock function - in a real application, this would query a database
    balances = {
        "1234": 5432.10,
        "5678": 10245.33,
        "9012": 750.25,
        "default": 1000.00
    }
    return balances.get(account_id, balances["default"])


@function_tool
def calculate_loan_payment(principal: float, interest_rate: float, years: int) -> float:
    """Calculate monthly payment for a loan."""
    # Convert annual interest rate to monthly rate and convert years to months
    monthly_rate = interest_rate / 100 / 12
    months = years * 12
    
    # Calculate monthly payment using the loan payment formula
    if monthly_rate == 0:
        return principal / months
    else:
        return principal * monthly_rate * (1 + monthly_rate) ** months / ((1 + monthly_rate) ** months - 1)


@function_tool
def calculate_investment_return(principal: float, annual_return_rate: float, years: int) -> float:
    """Calculate the future value of an investment."""
    # Simple compound interest calculation
    return principal * (1 + annual_return_rate / 100) ** years


def banking_handoff_message_filter(handoff_message_data: HandoffInputData) -> HandoffInputData:
    # Remove any tool-related messages from the message history
    handoff_message_data = handoff_filters.remove_all_tools(handoff_message_data)
    
    # Keep the full conversation history for the banking specialist
    return handoff_message_data


# Banking-themed agents
general_agent = Agent(
    name="Banking Assistant",
    instructions="You are a helpful banking assistant. Be concise and professional.",
    model=OpenAIChatCompletionsModel(
        model="gpt-4o",
        openai_client=openai_client
    ),
    tools=[check_account_balance],
)

loan_specialist_agent = Agent(
    name="Loan Specialist",
    instructions="""You are a loan specialist at a bank. 
    Focus on helping customers understand loan options, calculate payments, and assess affordability.
    Always ask for income information to provide personalized advice.
    Be professional, thorough, and explain financial terms clearly.""",
    model=OpenAIChatCompletionsModel(
        model="gpt-4o",
        openai_client=openai_client
    ),
    tools=[calculate_loan_payment],
)

investment_specialist_agent = Agent(
    name="Investment Specialist",
    instructions="""You are an investment specialist at a bank.
    Help customers understand investment options, risk profiles, and portfolio diversification.
    Always consider the customer's financial goals and risk tolerance.
    Be professional and explain investment concepts in clear terms.""",
    model=OpenAIChatCompletionsModel(
        model="gpt-4o",
        openai_client=openai_client
    ),
    tools=[calculate_investment_return],
)

customer_service_agent = Agent(
    name="Customer Service Agent",
    instructions="""You are a customer service agent at a bank.
    Help customers with general inquiries and direct them to specialists when needed.
    If the customer asks about loans or mortgages, handoff to the Loan Specialist.
    If the customer asks about investments or portfolio management, handoff to the Investment Specialist.
    Be professional, friendly, and helpful.""",
    model=OpenAIChatCompletionsModel(
        model="gpt-4o",
        openai_client=openai_client
    ),
    handoffs=[
        handoff(loan_specialist_agent, input_filter=banking_handoff_message_filter),
        handoff(investment_specialist_agent, input_filter=banking_handoff_message_filter),
    ],
    tools=[check_account_balance],
)


async def main():
    # Trace the entire run as a single workflow
        print("\n=== Banking Assistant Demo ===\n")
        
        # 1. Send a regular message to the general agent
        print("Step 1: Initial greeting")
        result = await Runner.run(general_agent, input="Hi, I'd like to check my account balance.")
        print(f"\nResponse: {result.final_output}\n")

        # 2. Check account balance with customer service
        print("\nStep 2: Checking account balance")
        result = await Runner.run(
            customer_service_agent,
            input=result.to_input_list()
            + [{"content": "Can you check the balance for account 1234?", "role": "user"}],
        )
        print(f"\nResponse: {result.final_output}\n")

        # 3. Ask about loans (should trigger handoff to loan specialist)
        print("\nStep 3: Loan inquiry (should trigger handoff to loan specialist)")
        result = await Runner.run(
            customer_service_agent,
            input=result.to_input_list()
            + [
                {
                    "content": "I'm interested in taking out a mortgage loan. Can you help me understand my options?",
                    "role": "user",
                }
            ],
        )
        print(f"\nResponse: {result.final_output}\n")

        # 4. Ask the loan specialist about payment calculations
        print("\nStep 4: Loan payment calculation")
        result = await Runner.run(
            customer_service_agent,
            input=result.to_input_list()
            + [
                {
                    "content": "If I borrow $300,000 at 4.5% interest for 30 years, what would my monthly payment be?",
                    "role": "user",
                }
            ],
        )
        print(f"\nResponse: {result.final_output}\n")
        
        # 5. Start a new conversation about investments (should trigger handoff to investment specialist)
        print("\nStep 5: Investment inquiry (should trigger handoff to investment specialist)")
        result = await Runner.run(
            customer_service_agent,
            input=[{"content": "I'm interested in investing some money. What options do you recommend?", "role": "user"}],
        )
        print(f"\nResponse: {result.final_output}\n")
        
        # 6. Ask about investment returns
        print("\nStep 6: Investment return calculation")
        result = await Runner.run(
            customer_service_agent,
            input=result.to_input_list()
            + [
                {
                    "content": "If I invest $50,000 with an expected 7% annual return, how much would I have after 10 years?",
                    "role": "user",
                }
            ],
        )
        print(f"\nResponse: {result.final_output}\n")

        result = await Runner.run(
            customer_service_agent,
            input=result.to_input_list()
            + [
                {
                    "content": "Give me my balance ?",
                    "role": "user",
                }
            ],
        )
        print(f"\nResponse: {result.final_output}\n")




asyncio.run(main())