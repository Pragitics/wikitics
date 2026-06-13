class S3DocumentStorageAdapter:
    """Boundary placeholder for S3/MinIO storage.

    Docker development currently uses LocalDocumentStorageAdapter. This class
    keeps the S3 adapter seam explicit for production implementation.
    """

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError("S3 storage adapter is not enabled in the MVP runtime")
