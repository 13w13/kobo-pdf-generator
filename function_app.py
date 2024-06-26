import logging
import requests
import azure.functions as func
from azure.storage.blob import BlobServiceClient
import os
import asyncio
from pyppeteer import launch
import json

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

WAIT_TIME = 20  # seconds

async def fetch_and_convert_to_pdf(login_url, view_url, username, password, headers, blob_service_client, container_name, submission_id):
    browser = await launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
    page = await browser.newPage()

    # 1. Navigate to login page
    logging.info(f"Navigating to login URL")
    await page.goto(login_url, {'waitUntil': 'networkidle2', 'timeout': 60000})
    await page.type('input[name="login"]', username)
    await page.type('input[name="password"]', password)
    await page.click('button[type="submit"]')
    await page.waitForNavigation({'waitUntil': 'networkidle2'})
    login_screenshot = await page.screenshot({'encoding': 'binary'})
    logging.info(f"Login screenshot saved")

    # Upload login screenshot
    login_screenshot_blob_name = f'{submission_id}_login_screenshot.png'
    login_screenshot_blob_client = blob_service_client.get_blob_client(container=container_name, blob=login_screenshot_blob_name)
    login_screenshot_blob_client.upload_blob(login_screenshot, blob_type="BlockBlob", overwrite=True)
    login_screenshot_url = login_screenshot_blob_client.url

    # 2. Fetch the view URL
    await page.setExtraHTTPHeaders(headers)
    logging.info(f"Fetching view URL")
    await page.goto(view_url, {'waitUntil': 'networkidle2', 'timeout': 60000})
    initial_screenshot = await page.screenshot({'encoding': 'binary'})
    logging.info(f"Initial screenshot saved")

    # Upload initial screenshot
    initial_screenshot_blob_name = f'{submission_id}_initial_screenshot.png'
    initial_screenshot_blob_client = blob_service_client.get_blob_client(container=container_name, blob=initial_screenshot_blob_name)
    initial_screenshot_blob_client.upload_blob(initial_screenshot, blob_type="BlockBlob", overwrite=True)
    initial_screenshot_url = initial_screenshot_blob_client.url

    # Ensure the page has content
    content = await page.content()
    logging.info(f"Initial page content length: {len(content)}")

    # Extract the view URL from the response
    response_json = await page.evaluate("document.body.innerText")
    logging.info(f"Response JSON fetched")
    data = json.loads(response_json)
    final_view_url = data.get('url')
    if not final_view_url:
        logging.error("Failed to fetch the final view URL")
        await browser.close()
        return None, login_screenshot_url, initial_screenshot_url, None

    # 3. Navigate to final view URL
    logging.info(f"Navigating to final view URL")
    await page.goto(final_view_url, {'waitUntil': 'networkidle2', 'timeout': 60000})
    await asyncio.sleep(WAIT_TIME)
    final_screenshot = await page.screenshot({'encoding': 'binary'})
    logging.info(f"Final screenshot saved")

    # Upload final screenshot
    final_screenshot_blob_name = f'{submission_id}_final_screenshot.png'
    final_screenshot_blob_client = blob_service_client.get_blob_client(container=container_name, blob=final_screenshot_blob_name)
    final_screenshot_blob_client.upload_blob(final_screenshot, blob_type="BlockBlob", overwrite=True)
    final_screenshot_url = final_screenshot_blob_client.url

    # Ensure the page has content
    content = await page.content()
    logging.info(f"Final page content length: {len(content)}")

    # Generate PDF
    pdf = await page.pdf({'format': 'A4'})
    await browser.close()
    return pdf, login_screenshot_url, initial_screenshot_url, final_screenshot_url

@app.function_name(name="HttpTrigger")
@app.route(route="http_trigger")
async def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    try:
        req_body = req.get_json()
        logging.info("Received request body")
    except ValueError:
        logging.error("Error parsing request body")
        return func.HttpResponse(
            "Invalid request body",
            status_code=400
        )

    kobo_server = req_body.get('kobo_server')
    username = req_body.get('username')
    password = req_body.get('password')
    kobo_api_token = req_body.get('kobo_api_token')
    asset_id = req_body.get('asset_id')
    submission_id = req_body.get('submission_id')

    if not all([kobo_server, username, password, kobo_api_token, asset_id, submission_id]):
        logging.error("Missing required parameters")
        return func.HttpResponse(
            "Please pass the kobo_server, username, password, kobo_api_token, asset_id, and submission_id in the request body",
            status_code=400
        )

    login_url = f"https://{kobo_server}/accounts/login/"
    view_url = f"https://{kobo_server}/api/v2/assets/{asset_id}/data/{submission_id}/enketo/view/"
    headers = {
        "Authorization": f"Token {kobo_api_token}",
        "Accept": "application/json"
    }

    try:
        # Initialize Blob Service Client
        connect_str = os.getenv('AzureWebJobsStorage')
        blob_service_client = BlobServiceClient.from_connection_string(connect_str)
        container_name = 'pdfs'

        # Fetch and convert the HTML content to PDF using pyppeteer
        pdf, login_screenshot_url, initial_screenshot_url, final_screenshot_url = await fetch_and_convert_to_pdf(
            login_url, view_url, username, password, headers, blob_service_client, container_name, submission_id)

        if pdf is None:
            return func.HttpResponse(
                "Error generating PDF from the provided HTML and CSS",
                status_code=500
            )

        # Upload PDF
        blob_name = f'{submission_id}.pdf'
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
        blob_client.upload_blob(pdf, blob_type="BlockBlob", overwrite=True)

        return func.HttpResponse(
            json.dumps({
                "pdf_url": blob_client.url,
                "login_screenshot_url": login_screenshot_url,
                "initial_screenshot_url": initial_screenshot_url,
                "final_screenshot_url": final_screenshot_url
            }),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return func.HttpResponse(
            f"Error generating PDF: {str(e)}",
            status_code=500
        )
