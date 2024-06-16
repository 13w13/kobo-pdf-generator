import logging
import requests
import azure.functions as func
from azure.storage.blob import BlobServiceClient
import os
import asyncio
from pyppeteer import launch
import json

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

WAIT_TIME = 10  # seconds

async def fetch_and_convert_to_pdf(login_url, view_url, username, password, headers):
    browser = await launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
    page = await browser.newPage()

    # 1. Navigate to login page
    logging.info(f"Navigating to login URL")
    await page.goto(login_url, {'waitUntil': 'networkidle2', 'timeout': 60000})
    await page.type('input[name="login"]', username)
    await page.type('input[name="password"]', password)
    await page.click('button[type="submit"]')
    await page.waitForNavigation({'waitUntil': 'networkidle2'})
    login_screenshot_path = f'/tmp/login_screenshot.png'
    await page.screenshot({'path': login_screenshot_path})
    logging.info(f"Login screenshot saved")

    # 2. Fetch the view URL
    await page.setExtraHTTPHeaders(headers)
    logging.info(f"Fetching view URL")
    await page.goto(view_url, {'waitUntil': 'networkidle2', 'timeout': 60000})
    initial_screenshot_path = f'/tmp/initial_screenshot.png'
    await page.screenshot({'path': initial_screenshot_path})
    logging.info(f"Initial screenshot saved")

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
        return None, login_screenshot_path, initial_screenshot_path, None

    # 3. Navigate to final view URL
    logging.info(f"Navigating to final view URL")
    await page.goto(final_view_url, {'waitUntil': 'networkidle2', 'timeout': 60000})
    await asyncio.sleep(WAIT_TIME)
    final_screenshot_path = f'/tmp/final_screenshot.png'
    await page.screenshot({'path': final_screenshot_path})
    logging.info(f"Final screenshot saved")

    # Ensure the page has content
    content = await page.content()
    logging.info(f"Final page content length: {len(content)}")

    # Generate PDF
    pdf = await page.pdf({'format': 'A4'})
    await browser.close()
    return pdf, login_screenshot_path, initial_screenshot_path, final_screenshot_path

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
        # Fetch and convert the HTML content to PDF using pyppeteer
        pdf, login_screenshot_path, initial_screenshot_path, final_screenshot_path = await fetch_and_convert_to_pdf(
            login_url, view_url, username, password, headers)

        if pdf is None:
            return func.HttpResponse(
                "Error generating PDF from the provided HTML and CSS",
                status_code=500
            )

        # Upload to Azure Blob Storage
        connect_str = os.getenv('AzureWebJobsStorage')
        blob_service_client = BlobServiceClient.from_connection_string(connect_str)
        container_name = 'pdfs'

        blob_name = f'{submission_id}.pdf'
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

        # Upload the blob, overwrite if it already exists
        blob_client.upload_blob(pdf, blob_type="BlockBlob", overwrite=True)

        return func.HttpResponse(
            json.dumps({
                "pdf_url": blob_client.url
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
