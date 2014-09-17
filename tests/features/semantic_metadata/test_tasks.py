import unittest
import os
import tempfile
import shutil

from moto import mock_s3
import boto

from cdf.utils.hashing import string_to_int32
from cdf.features.semantic_metadata.metadata_duplicate import notset_hash_value
from cdf.features.main.streams import ZoneStreamDef, StrategicUrlStreamDef
from cdf.features.semantic_metadata.streams import (
    ContentsCountStreamDef,
    ContentsDuplicateStreamDef,
    ContentsContextAwareDuplicateStreamDef,
    ContentsStreamDef
)
from cdf.features.semantic_metadata.tasks import (
    compute_metadata_count,
    make_metadata_duplicates_file,
    make_context_aware_metadata_duplicates_file
)


class TestComputeMetadataCount(unittest.TestCase):
    def setUp(self):
        self.bucket_name = "app.foo.com"
        self.s3_uri = "s3://{}/crawl_result".format(self.bucket_name)

        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    @mock_s3
    def test_nominal_case(self):
        conn = boto.connect_s3()
        bucket = conn.create_bucket(self.bucket_name)
        part_id = 1

        #create urlcontents
        urlcontents = boto.s3.key.Key(bucket)
        urlcontents.key = "crawl_result/urlcontents.txt.{}.gz".format(part_id)
        fake_hash = 1597530492

        contents = [
            (1, 1, fake_hash, "foo title"),
            (1, 2, fake_hash, "foo description"),
            (1, 3, fake_hash, "foo h1"),
            (1, 1, fake_hash, "bar title"),
            (1, 3, fake_hash, "bar h1"),
            (1, 4, notset_hash_value, "not set h2"),
            (2, 1, fake_hash, "foo title 2")
        ]
        ContentsStreamDef.persist(
            iter(contents),
            self.s3_uri,
            part_id=part_id
        )

        #actual call
        file_uri = compute_metadata_count(self.s3_uri, part_id)

        #check results
        expected_file_uri = os.path.join(
            self.s3_uri,
            "{}.txt.{}.gz".format(ContentsCountStreamDef.FILE, part_id)
        )
        self.assertEqual(
            expected_file_uri,
            file_uri
        )
        expected_stream = [
            [1, 1, 2],
            [1, 2, 1],
            [1, 3, 2],
            [2, 1, 1]
        ]
        actual_stream = ContentsCountStreamDef.load(
            self.s3_uri,
            tmp_dir=self.tmp_dir,
            part_id=part_id
        )
        self.assertEqual(expected_stream, list(actual_stream))


class TestComputeMetadataDuplicateFile(unittest.TestCase):
    def setUp(self):
        self.bucket_name = "app.foo.com"
        self.s3_uri = "s3://{}/crawl_result".format(self.bucket_name)
        self.crawl_id = 10
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    @mock_s3
    def test_nominal_case(self):
        conn = boto.connect_s3()
        bucket = conn.create_bucket(self.bucket_name)

        first_part_size = 5
        part_size = 10

        contents = [
            (1, 1, string_to_int32("title1"), "title1"),
            (1, 4, string_to_int32("description1"), "description1"),
            (2, 1, string_to_int32("title2"), "title2"),
            (6, 1, string_to_int32("title1"), "title1"),
            (6, 4, string_to_int32("description2"), "description2"),
            (8, 4, string_to_int32("description1"), "description1"),
            (9, 4, string_to_int32("description1"), "description1")
        ]
        ContentsStreamDef.persist(
            iter(contents),
            self.s3_uri,
            first_part_size=first_part_size,
            part_size=part_size
        )

        output_files = make_metadata_duplicates_file(
            self.crawl_id,
            self.s3_uri,
            first_part_size,
            part_size
        )

        expected_output_files = [
            os.path.join(self.s3_uri, "urlcontentsduplicate.txt.0.gz"),
            os.path.join(self.s3_uri, "urlcontentsduplicate.txt.1.gz"),
        ]
        self.assertItemsEqual(expected_output_files, output_files)

        duplicate_stream = ContentsDuplicateStreamDef.load(
            self.s3_uri,
            tmp_dir=self.tmp_dir
        )

        expected_stream = [
            [1, 1, 2, True, [6]],
            [1, 4, 3, True, [8, 9]],
            [2, 1, 0, True, []],
            [6, 1, 2, False, [1]],
            [6, 4, 0, True, []],
            [8, 4, 3, False, [1, 9]],
            [9, 4, 3, False, [1, 8]]
        ]
        self.assertEqual(expected_stream, list(duplicate_stream))


class TestMakeContextAwareMetadataDuplicatesFile(unittest.TestCase):
    def setUp(self):
        self.bucket_name = "app.foo.com"
        self.s3_uri = "s3://{}/crawl_result".format(self.bucket_name)
        self.crawl_id = 10
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    @mock_s3
    def test_nominal_case(self):
        conn = boto.connect_s3()
        bucket = conn.create_bucket(self.bucket_name)

        first_part_size = 2
        part_size = 10

        contents = iter((
            [1, 2, string_to_int32('My first H1'), 'My first H1'],
            [1, 3, string_to_int32('My H2'), 'My H2'],
            [1, 1, string_to_int32('My title'), 'My title'],
            [1, 4, string_to_int32('My Desc'), 'My Desc'],
            [2, 2, string_to_int32('My first H1'), 'My first H1'],
            [2, 4, string_to_int32('My Desc'), 'My Desc'],
            [3, 1, string_to_int32('My title'), 'My title'],
            [3, 2, string_to_int32('My second H1'), 'My second H1'],
            [3, 4, string_to_int32('My Desc'), 'My Desc'],
        ))
        ContentsStreamDef.persist(
            iter(contents),
            self.s3_uri,
            first_part_size=first_part_size,
            part_size=part_size
        )

        zones = iter([
            (1, "en-US,https"),
            (2, "en-US,https"),
            (3, "en-US,https")
        ])
        ZoneStreamDef.persist(
            iter(zones),
            self.s3_uri,
            first_part_size=first_part_size,
            part_size=part_size
        )

        strategic_urls = iter([
            (1, True, 0),
            (2, False, 0),
            (3, True, 0)
        ])
        StrategicUrlStreamDef.persist(
            iter(strategic_urls),
            self.s3_uri,
            first_part_size=first_part_size,
            part_size=part_size
        )
        output_files = make_context_aware_metadata_duplicates_file(self.s3_uri,
                                                                first_part_size,
                                                                part_size)

        expected_output_files = [
            os.path.join(self.s3_uri, "urlcontentsduplicate_contextaware.txt.0.gz"),
            os.path.join(self.s3_uri, "urlcontentsduplicate_contextaware.txt.1.gz"),
        ]

        self.assertEqual(expected_output_files, output_files)

        actual_stream = ContentsContextAwareDuplicateStreamDef.load(
            self.s3_uri,
            tmp_dir=self.tmp_dir
        )
        expected_stream = [
            [1, 1, 2, True, [3]],
            [1, 2, 0, True, []],
            [1, 4, 2, True, [3]],
            [3, 1, 2, False, [1]],
            [3, 2, 0, True, []],
            [3, 4, 2, False, [1]]
        ]
        self.assertEqual(expected_stream, list(actual_stream))