import os, sys, re
from fastapi import FastAPI, UploadFile

sys.path.append(os.path.dirname(__file__))
from server_tools.server_utils import logger, del_older_files, BaseResponse
from server_tools.parse_tools import Unstructured2MD, FileVerify

app = FastAPI()
file_verify = FileVerify()
unstructured2md = Unstructured2MD()

LOADER_LIST = [".docx", ".txt", ".pdf", ".xlsx", ".xls", ".csv", ".pptx", ".ppt", ".html", ".json",
               ".xml", ".epub", ".png", ".jpg", ".jpeg", ".bmp"]


@app.post(
    "/knowledge_base/doc_parse",
    tags=["projects"],
    summary="Parse PDF/word/excel/ppt/txt files (supports local files and S3)",
)
async def markify_parse(
        file_bytes: UploadFile = None,
        file_path: str = None,
):
    """
    Execute the process of converting PDF to JSON and MD, outputting MD and JSON files
    to the specified directory.

    Args:
        file_bytes: The PDF file to be parsed. Must not be specified together with
            `pdf_path`
        file_path: The path to the PDF file to be parsed. Must not be specified together
            with `pdf_file`
    """
    try:
        if (file_bytes is None and file_path is None) or (
                file_bytes is not None and file_path is not None
        ):
            msg = "Must provide either file_bytes or file_path"
            logger.warning(msg)
            return BaseResponse(
                msg=msg,
                code=400,
            )
        # Get PDF filename
        base_name = os.path.basename(file_path if file_path else file_bytes.filename)
        file_name = base_name.split(".")[0]
        ext = os.path.splitext(base_name)[-1].lower()
        if ext not in LOADER_LIST:
            msg = f"Format not supported: {base_name}"
            logger.warning(msg)
            return BaseResponse(
                msg=msg,
                code=400,
            )
        output_root = f"{os.path.dirname(__file__)}/../output"
        output_dir = f"{output_root}/{file_name}"
        output_file_path = f"{output_dir}/{base_name}"
        output_image_path = f"{output_dir}/images"
        # Initialize readers/writers and get content
        writer, image_writer, pdf_bytes = unstructured2md.init_writers(
            pdf_path=file_path,
            pdf_file=file_bytes,
            output_dir=output_dir,
            output_image_path=output_image_path,
        )
        writer.write(output_file_path, pdf_bytes)
        if not file_verify.verify(output_file_path):
            msg = f"File verification failed: {base_name}"
            logger.warning(msg)
            return BaseResponse(code=400, msg=msg)

        if ext == ".pdf":
            md_content = unstructured2md.pdf_parse(pdf_bytes, image_writer)
        else:
            md_content = unstructured2md.markitdown_parse(output_file_path)
        if md_content is None:
            msg = f"Error processed {base_name}"
            logger.warning(msg)
            return BaseResponse(msg=msg, code=400)
        # replace img link
        md_content_text = re.sub(r'!\[.*?\]\(.*?\)', '', md_content)
        md_content_text = md_content_text.strip()
        writer.write_string(f"{output_file_path}.md", md_content_text)
        del_older_files(output_dir)
        msg = f"Successfully processed {base_name}"
        logger.info(msg)
        return BaseResponse(code=200, data=md_content_text, msg=msg)
    except Exception as e:
        msg = f"Error: {str(e)}"
        logger.error(msg)
        return BaseResponse(msg=msg, code=500)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8562)
