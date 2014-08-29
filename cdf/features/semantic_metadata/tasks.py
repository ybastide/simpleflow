import itertools
from cdf.log import logger
from cdf.analysis.urls.transducers.metadata_duplicate import (
    get_duplicate_metadata,
    get_zone_aware_duplicate_metadata,
    count_metadata
)
from cdf.features.semantic_metadata.streams import (
    ContentsStreamDef,
    ContentsDuplicateStreamDef,
    ContentsZoneAwareDuplicateStreamDef,
    ContentsCountStreamDef
)
from cdf.features.main.streams import (
    ZoneStreamDef,
    StrategicUrlStreamDef
)
from cdf.tasks.decorators import TemporaryDirTask as with_temporary_dir
from cdf.tasks.constants import DEFAULT_FORCE_FETCH


@with_temporary_dir
def compute_metadata_count(s3_uri, part_id, tmp_dir=None):
    contents_stream = ContentsStreamDef.get_stream_from_s3(
        s3_uri,
        part_id=part_id,
        tmp_dir=tmp_dir
    )
    output_stream = count_metadata(contents_stream, part_id)

    s3_destination = ContentsCountStreamDef.persist_part_to_s3(
        output_stream,
        s3_uri,
        part_id=part_id
    )

    return s3_destination


def to_string(row):
    """Format a row from get_duplicate_metadata() so that
    it can be processed by persist_to_s3()
    It transforms the booleans in integer
    and the lists in strings.
    """
    url_id, metadata_type, duplicates_nb, is_first, target_urls_ids = row
    return (url_id,
            metadata_type,
            duplicates_nb,
            1 if is_first else 0,
            ';'.join(str(u) for u in target_urls_ids)
           )


@with_temporary_dir
def make_metadata_duplicates_file(crawl_id, s3_uri,
                                  first_part_id_size, part_id_size,
                                  tmp_dir=None,
                                  force_fetch=DEFAULT_FORCE_FETCH):
    logger.info('Fetching contents stream from S3')
    contents_stream = ContentsStreamDef.get_stream_from_s3(s3_uri,
                                                           tmp_dir=tmp_dir)
    generator = get_duplicate_metadata(contents_stream)
    generator = itertools.imap(to_string, generator)
    files = ContentsDuplicateStreamDef.persist_to_s3(generator,
                                                     s3_uri,
                                                     first_part_id_size,
                                                     part_id_size)
    return files


@with_temporary_dir
def make_zone_aware_metadata_duplicates_file(s3_uri,
                                             first_part_id_size,
                                             part_id_size,
                                             tmp_dir=None,
                                             force_fetch=DEFAULT_FORCE_FETCH):
    """Compute zone aware duplicates.
    :param s3_uri: the uri where the crawl data is stored.
    :type s3_uri: str
    :param first_part_id_size: the size of the first partition
    :type first_part_id_size: int
    :param part_id_size: the size of all other partitions
    :type part_id_size: int
    :param tmp_dir: the directory where to save temporary data
    :type tmp_dir: str
    :param force_fetch: if True, the files will be downloaded from s3
    """
    logger.info('Fetching contents stream from S3')
    contents_stream = ContentsStreamDef.get_stream_from_s3(
        s3_uri,
        tmp_dir=tmp_dir
    )
    zone_stream = ZoneStreamDef.get_stream_from_s3(s3_uri, tmp_dir=tmp_dir)
    strategic_urls_stream = StrategicUrlStreamDef.get_stream_from_s3(
        s3_uri,
        tmp_dir=tmp_dir
    )

    generator = get_zone_aware_duplicate_metadata(
        contents_stream,
        zone_stream,
        strategic_urls_stream
    )
    generator = itertools.imap(to_string, generator)
    files = ContentsZoneAwareDuplicateStreamDef.persist_to_s3(generator,
                                                              s3_uri,
                                                              first_part_id_size,
                                                              part_id_size)
    return files
