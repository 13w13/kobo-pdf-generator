# KoboToolbox PDF Generator

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

An Azure Function to automatically generate PDFs from KoboToolbox submissions and store them in Azure Blob Storage. This project is aimed at humanitarian organizations using KoboToolbox to simplify the process of generating and managing submission PDFs.

## Overview

The KoboToolbox PDF Generator function app is designed to streamline the process of converting KoboToolbox submissions into PDFs when a new submission is recorded trough REST API and storing them securely in Azure Blob Storage. The function supports different KoboToolbox servers and can be easily configured for various environments and credentials.

## Setting Up Your Own Azure Function and Blob Storage

### Prerequisites

- Python 3.10
- Azure Functions Core Tools
- Azure Storage Account

### Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/your-github-username/kobo-pdf-generator.git
   cd kobo-pdf-generator


## Setting Up Your Own Azure Function and Blob Storage

### Prerequisites

- Python 3.10
- Azure Functions Core Tools
- Azure Storage Account

### Installation

1. **Clone the Repository**:
    ```bash
    git clone https://github.com/your-github-username/kobo-pdf-generator.git
    cd kobo-pdf-generator
    ```

2. **Install Requirements**:
    ```bash
    pip install -r requirements.txt
    ```

3. **Configure Azure Function**:

    Set environment variables for AzureWebJobsStorage.
    Deploy the function to Azure.

### Deployment

1. **Login to Azure**:
    ```bash
    az login
    ```

2. **Deploy the Function**:
    ```bash
    func azure function publish <YourFunctionAppName>
    ```

## Using the API Endpoint

POST /api/http_trigger

### Request Body

```json
{
  "kobo_server": "your_kobo_server",
  "username": "your_username",
  "password": "your_password",
  "kobo_api_token": "your_kobo_api_token",
  "asset_id": "your_asset_id",
  "submission_id": "your_submission_id"
}
```
### Response
```json
{
  "pdf_url": "https://your-storage-account.blob.core.windows.net/pdfs/submission_id.pdf"
}
```

### Request Access Token

If you wish to use the API for testing, access can be provided through an access token to call the POST function. Please request access via this form. We will get back to you quickly.

### License
This project is licensed under the MIT License.

### Creator
Created by 13w.