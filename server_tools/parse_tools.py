import fitz
import os, sys
from io import StringIO
from typing import Tuple, Union
from markitdown import MarkItDown
from fastapi import UploadFile
import pandas as pd
from rapidocr_onnxruntime import RapidOCR

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import base_config
from server_tools.server_utils import logger
import magic_pdf.model as model_config
from magic_pdf.config.enums import SupportedPdfParseMethod
from magic_pdf.data.data_reader_writer import DataWriter, FileBasedDataWriter
from magic_pdf.data.data_reader_writer.s3 import S3DataReader, S3DataWriter
from magic_pdf.data.dataset import PymuDocDataset
from magic_pdf.libs.config_reader import get_bucket_name, get_s3_config
from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze
from magic_pdf.operators.models import InferenceResult
from magic_pdf.operators.pipes import PipeResult

model_config.__use_inside_model__ = True


class MemoryDataWriter(DataWriter):
    def __init__(self):
        self.buffer = StringIO()

    def write(self, path: str, data: bytes) -> None:
        if isinstance(data, str):
            self.buffer.write(data)
        else:
            self.buffer.write(data.decode("utf-8"))

    def write_string(self, path: str, data: str) -> None:
        self.buffer.write(data)

    def get_value(self) -> str:
        return self.buffer.getvalue()

    def close(self):
        self.buffer.close()


class FileVerify:
    def __init__(self, ):
        self.MAX_PAGES = base_config.MAX_PAGES
        self.MIN_CTX = base_config.MIN_CTX
        self.MAX_CTX = base_config.MAX_CTX
        self.MAX_SIZE = base_config.MAX_SIZE

    # 判断上传文件是否合规：大小，字数， 页数。
    def bool_size_ok(self, filepath) -> bool:
        size_in_bytes = os.path.getsize(filepath)
        size_in_mb = size_in_bytes / (1024 * 1024)
        size_round = round(size_in_mb, 2)
        file_size_ok = size_round <= self.MAX_SIZE
        return file_size_ok

    def bool_pages_ok(self, filepath) -> bool:
        page_count = 0
        # only for pdf
        if filepath.endswith(".pdf"):
            pdf_doc = fitz.open(filepath)
            page_count = pdf_doc.page_count
        file_pages_ok = page_count <= self.MAX_PAGES
        return file_pages_ok

    def bool_tokens_ok(self, context) -> bool:
        num_tokens = len(context)
        file_ctx_ok = num_tokens <= self.MAX_CTX
        return file_ctx_ok

    def verify(self, filepath) -> bool:
        # 暂时不做ctx判断
        file_size_ok = self.bool_size_ok(filepath)
        file_pages_ok = self.bool_pages_ok(filepath)
        file_verify_ok = file_size_ok and file_pages_ok
        return file_verify_ok


class Unstructured2MD:
    def __init__(self, ):
        self.markitdown = MarkItDown()  # Set to True to enable plugins
        self.img_ocr = RapidOCR()

    def init_writers(
            self,
            pdf_path: str = None,
            pdf_file: UploadFile = None,
            output_dir: str = None,
            output_image_path: str = None,
    ) -> Tuple[
        Union[S3DataWriter, FileBasedDataWriter],
        Union[S3DataWriter, FileBasedDataWriter],
        bytes,
    ]:
        """
        Initialize writers based on path type

        Args:
            pdf_path: PDF file path (local path or S3 path)
            pdf_file: Uploaded PDF file object
            output_path: Output directory path
            output_image_path: Image output directory path

        Returns:
            Tuple[writer, image_writer, pdf_bytes]: Returns initialized writer tuple and PDF
            file content
        """
        if pdf_path:
            is_s3_path = pdf_path.startswith("s3://")
            if is_s3_path:
                bucket = get_bucket_name(pdf_path)
                ak, sk, endpoint = get_s3_config(bucket)

                writer = S3DataWriter(
                    output_dir, bucket=bucket, ak=ak, sk=sk, endpoint_url=endpoint
                )
                image_writer = S3DataWriter(
                    output_image_path, bucket=bucket, ak=ak, sk=sk, endpoint_url=endpoint
                )
                # 临时创建reader读取文件内容
                temp_reader = S3DataReader(
                    "", bucket=bucket, ak=ak, sk=sk, endpoint_url=endpoint
                )
                pdf_bytes = temp_reader.read(pdf_path)
            else:
                writer = FileBasedDataWriter(output_dir)
                image_writer = FileBasedDataWriter(output_image_path)
                os.makedirs(output_image_path, exist_ok=True)
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()
        else:
            # 处理上传的文件
            pdf_bytes = pdf_file.file.read()
            writer = FileBasedDataWriter(output_dir)
            image_writer = FileBasedDataWriter(output_image_path)
            os.makedirs(output_image_path, exist_ok=True)
        return writer, image_writer, pdf_bytes

    def process_pdf(
            self,
            pdf_bytes: bytes,
            parse_method: str,
            image_writer: Union[S3DataWriter, FileBasedDataWriter],
    ) -> Tuple[InferenceResult, PipeResult]:
        """
        Process PDF file content

        Args:
            pdf_bytes: Binary content of PDF file
            parse_method: Parse method ('ocr', 'txt', 'auto')
            image_writer: Image writer

        Returns:
            Tuple[InferenceResult, PipeResult]: Returns inference result and pipeline result
        """
        ds = PymuDocDataset(pdf_bytes)
        infer_result: InferenceResult = None
        pipe_result: PipeResult = None

        if parse_method == "ocr":
            infer_result = ds.apply(doc_analyze, ocr=True)
            pipe_result = infer_result.pipe_ocr_mode(image_writer)
        elif parse_method == "txt":
            infer_result = ds.apply(doc_analyze, ocr=False)
            pipe_result = infer_result.pipe_txt_mode(image_writer)
        else:  # auto
            if ds.classify() == SupportedPdfParseMethod.OCR:
                infer_result = ds.apply(doc_analyze, ocr=True)
                pipe_result = infer_result.pipe_ocr_mode(image_writer)
            else:
                infer_result = ds.apply(doc_analyze, ocr=False)
                pipe_result = infer_result.pipe_txt_mode(image_writer)

        return infer_result, pipe_result

    def pdf_parse(
            self,
            pdf_bytes: bytes,
            image_writer: Union[S3DataWriter, FileBasedDataWriter],
            parse_method: str = "auto",
    ):
        """
        Execute the process of converting PDF to JSON and MD, outputting MD and JSON files
        to the specified directory.

        Args:
            pdf_file: The PDF file to be parsed. Must not be specified together with
                `pdf_path`
            pdf_path: The path to the PDF file to be parsed. Must not be specified together
                with `pdf_file`
            parse_method: Parsing method, can be auto, ocr, or txt. Default is auto. If
                results are not satisfactory, try ocr
            output_dir: Output directory for results. A folder named after the PDF file
                will be created to store all results
        """
        try:
            # Process PDF
            infer_result, pipe_result = self.process_pdf(pdf_bytes, parse_method, image_writer)

            # Use MemoryDataWriter to get results
            content_list_writer = MemoryDataWriter()
            md_content_writer = MemoryDataWriter()
            middle_json_writer = MemoryDataWriter()

            # Use PipeResult's dump method to get data
            pipe_result.dump_content_list(content_list_writer, "", "images")
            pipe_result.dump_md(md_content_writer, "", "images")
            pipe_result.dump_middle_json(middle_json_writer, "")
            # Get content
            md_content = md_content_writer.get_value()

            # Clean up memory writers
            content_list_writer.close()
            md_content_writer.close()
            middle_json_writer.close()
            return md_content
        except Exception as e:
            logger.error(e)
            return None

    def markitdown_parse(
            self,
            file_path: str = None,
    ):
        """
        Execute the process of converting txt/docx/xlsx/xls to MD, outputting MD and JSON files
        to the specified directory.):
        """

        ext = os.path.splitext(file_path)[-1].lower()
        if ext == ".csv":
            df = pd.read_csv(file_path)
            save_path = file_path.replace(".csv", ".xlsx")
            df.to_excel(save_path, index=False)
        elif ext in [".png", ".jpg", ".jpeg", ".bmp"]:
            resp = ""
            save_path = file_path.replace(ext, ".txt")
            result, _ = self.img_ocr(file_path)
            if result:
                ocr_result = [line[1] for line in result]
                resp += "\n".join(ocr_result)
                with open(save_path, 'w', encoding='utf-8') as file:
                    file.write(resp)
        else:
            save_path = file_path
        if os.path.exists(save_path):
            result = self.markitdown.convert(save_path)
            return result.text_content
        else:
            logger.error(f"File not found: {save_path}")
            return None
