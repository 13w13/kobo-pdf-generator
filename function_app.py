import logging
import azure.functions as func
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
import os
import asyncio
from pyppeteer import launch
import json
from datetime import datetime, timedelta

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

WAIT_TIME = 300  # seconds
MAX_ATTEMPTS = 20
MIN_CONTENT_LENGTH = 1000

async def check_page_loaded(page):
    return await page.evaluate('''() => {
        const loadingIndicator = document.querySelector('.main-loader');
        if (loadingIndicator && window.getComputedStyle(loadingIndicator).display !== 'none') {
            return false;
        }
        return document.body.innerText.length > 1000;
    }''')

async def fetch_and_convert_to_pdf(login_url, view_url, username, password, headers, blob_service_client, container_name, submission_id):
    browser = None
    try:
        browser = await launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        page = await browser.newPage()

        logging.info("Navigating to login URL")
        await page.goto(login_url, {'waitUntil': 'networkidle2', 'timeout': 60000})
        await page.type('input[name="login"]', username)
        await page.type('input[name="password"]', password)
        await page.click('button[type="submit"]')
        await page.waitForNavigation({'waitUntil': 'networkidle2'})

        logging.info("Fetching view URL")
        await page.setExtraHTTPHeaders(headers)
        await page.goto(view_url, {'waitUntil': 'networkidle2', 'timeout': 60000})

        response_json = await page.evaluate("document.body.innerText")
        data = json.loads(response_json)
        final_view_url = data.get('url')
        if not final_view_url:
            raise ValueError("Failed to fetch the final view URL")

        logging.info(f"Navigating to final view URL: {final_view_url}")
        await page.goto(final_view_url, {'waitUntil': 'networkidle2', 'timeout': 60000})
        
        for attempt in range(MAX_ATTEMPTS):
            if await check_page_loaded(page):
                logging.info(f"Final view content loaded on attempt {attempt + 1}")
                break
            if attempt < MAX_ATTEMPTS - 1:
                logging.warning(f"Content not fully loaded, retrying (Attempt {attempt + 1}/{MAX_ATTEMPTS})")
                await asyncio.sleep(WAIT_TIME / MAX_ATTEMPTS)
        else:
            raise TimeoutError("Failed to load final view content after multiple attempts")

        await asyncio.sleep(5)  # Extra wait for any final rendering

        final_screenshot = await page.screenshot({'encoding': 'binary', 'fullPage': True})
        pdf = await page.pdf({'format': 'A4', 'printBackground': True})

        return pdf, final_screenshot, final_view_url

    finally:
        if browser:
            await browser.close()

def upload_blob(blob_client, data):
    blob_client.upload_blob(data, blob_type="BlockBlob", overwrite=True)
    return blob_client.url

@app.function_name(name="HttpTrigger")
@app.route(route="http_trigger")
async def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        kobo_server = req_body['kobo_server']
        username = req_body['username']
        password = req_body['password']
        kobo_api_token = req_body['kobo_api_token']
        asset_id = req_body['asset_id']
        submission_id = req_body['submission_id']

        login_url = f"https://{kobo_server}/accounts/login/"
        view_url = f"https://{kobo_server}/api/v2/assets/{asset_id}/data/{submission_id}/enketo/view/"
        headers = {"Authorization": f"Token {kobo_api_token}", "Accept": "application/json"}

        connect_str = os.environ['AzureWebJobsStorage']
        blob_service_client = BlobServiceClient.from_connection_string(connect_str)
        container_name = 'pdfs'

        pdf, screenshot, final_view_url = await fetch_and_convert_to_pdf(
            login_url, view_url, username, password, headers, blob_service_client, container_name, submission_id)

        pdf_blob_name = f'{submission_id}.pdf'
        screenshot_blob_name = f'{submission_id}_screenshot.png'

        pdf_blob_client = blob_service_client.get_blob_client(container=container_name, blob=pdf_blob_name)
        screenshot_blob_client = blob_service_client.get_blob_client(container=container_name, blob=screenshot_blob_name)

        # Upload blobs without using await
        pdf_url = upload_blob(pdf_blob_client, pdf)
        screenshot_url = upload_blob(screenshot_blob_client, screenshot)

        account_name = os.environ['AZURE_STORAGE_ACCOUNT_NAME']
        account_key = os.environ['AZURE_STORAGE_ACCOUNT_KEY']
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=container_name,
            blob_name=pdf_blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(hours=1)
        )
        pdf_url_with_sas = f"{pdf_url}?{sas_token}"

        return func.HttpResponse(
            json.dumps({
                "pdf_url": pdf_url_with_sas,
                "screenshot_url": screenshot_url,
                "final_view_url": final_view_url
            }),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return func.HttpResponse(f"Error generating PDF: {str(e)}", status_code=500)