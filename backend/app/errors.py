class ApplicationError(Exception):
    status_code = 422


class UnsupportedDocumentType(ApplicationError):
    status_code = 415


class CorruptedDocument(ApplicationError):
    pass


class ParsingFailed(ApplicationError):
    pass


class OCRFailed(ApplicationError):
    pass


class ClassificationFailed(ApplicationError):
    pass


class EmbeddingFailed(ApplicationError):
    status_code = 503


class IndexingFailed(ApplicationError):
    status_code = 503


class ProviderFailed(ApplicationError):
    status_code = 503


class UploadTooLarge(ApplicationError):
    status_code = 413
