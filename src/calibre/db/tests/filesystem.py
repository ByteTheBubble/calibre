#!/usr/bin/env python


__license__   = 'GPL v3'
__copyright__ = '2013, Kovid Goyal <kovid at kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

import os
import time
import unittest
from io import BytesIO

from calibre.constants import iswindows
from calibre.db.tests.base import BaseTest
from calibre.ptempfile import TemporaryDirectory


def read(x, mode='r'):
    with open(x, mode) as f:
        return f.read()


class FilesystemTest(BaseTest):

    def get_filesystem_data(self, cache, book_id):
        fmts = cache.field_for('formats', book_id)
        ans = {}
        for fmt in fmts:
            buf = BytesIO()
            if cache.copy_format_to(book_id, fmt, buf):
                ans[fmt] = buf.getvalue()
        buf = BytesIO()
        if cache.copy_cover_to(book_id, buf):
            ans['cover'] = buf.getvalue()
        return ans

    def test_metadata_move(self):
        'Test the moving of files when title/author change'
        cl = self.cloned_library
        cache = self.init_cache(cl)
        ae, af, sf = self.assertEqual, self.assertFalse, cache.set_field

        # Test that changing metadata on a book with no formats/cover works
        ae(sf('title', {3:'moved1'}), {3})
        ae(sf('authors', {3:'moved1'}), {3})
        ae(sf('title', {3:'Moved1'}), {3})
        ae(sf('authors', {3:'Moved1'}), {3})
        ae(cache.field_for('title', 3), 'Moved1')
        ae(cache.field_for('authors', 3), ('Moved1',))

        # Now try with a book that has covers and formats
        orig_data = self.get_filesystem_data(cache, 1)
        orig_fpath = cache.format_abspath(1, 'FMT1')
        ae(sf('title', {1:'moved'}), {1})
        ae(sf('authors', {1:'moved'}), {1})
        ae(sf('title', {1:'Moved'}), {1})
        ae(sf('authors', {1:'Moved'}), {1})
        ae(cache.field_for('title', 1), 'Moved')
        ae(cache.field_for('authors', 1), ('Moved',))
        cache2 = self.init_cache(cl)
        for c in (cache, cache2):
            data = self.get_filesystem_data(c, 1)
            ae(set(orig_data), set(data))
            ae(orig_data, data, 'Filesystem data does not match')
            ae(c.field_for('path', 1), 'Moved/Moved (1)')
            ae(c.field_for('path', 3), 'Moved1/Moved1 (3)')
        fpath = c.format_abspath(1, 'FMT1').replace(os.sep, '/').split('/')
        ae(fpath[-3:], ['Moved', 'Moved (1)', 'Moved - Moved.fmt1'])
        af(os.path.exists(os.path.dirname(orig_fpath)), 'Original book folder still exists')
        # Check that the filesystem reflects fpath (especially on
        # case-insensitive systems).
        for x in range(1, 4):
            base = os.sep.join(fpath[:-x])
            part = fpath[-x:][0]
            self.assertIn(part, os.listdir(base))

        initial_side_data = {}
        def init_cache():
            nonlocal cache, initial_side_data
            cache = self.init_cache(self.cloned_library)
            bookdir = os.path.dirname(cache.format_abspath(1, '__COVER_INTERNAL__'))
            with open(os.path.join(bookdir, 'a.side'), 'w') as f:
                f.write('a.side')
            os.mkdir(os.path.join(bookdir, 'subdir'))
            with open(os.path.join(bookdir, 'subdir', 'a.fmt1'), 'w') as f:
                f.write('a.fmt1')
            initial_side_data = side_data()

        def side_data(book_id=1):
            bookdir = os.path.dirname(cache.format_abspath(book_id, '__COVER_INTERNAL__'))
            return {
                'a.side': read(os.path.join(bookdir, 'a.side')),
                'a.fmt1': read(os.path.join(bookdir, 'subdir', 'a.fmt1')),
            }

        def check_that_filesystem_and_db_entries_match(book_id):
            bookdir = os.path.dirname(cache.format_abspath(book_id, '__COVER_INTERNAL__'))
            if iswindows:
                from calibre_extensions import winutil
                bookdir = winutil.get_long_path_name(bookdir)
            bookdir_contents = set(os.listdir(bookdir))
            expected_contents = {'cover.jpg', 'a.side', 'subdir'}
            for fmt, fname in cache.fields['formats'].table.fname_map[book_id].items():
                expected_contents.add(fname + '.' + fmt.lower())
            ae(expected_contents, bookdir_contents)
            fs_path = bookdir.split(os.sep)[-2:]
            db_path = cache.field_for('path', book_id).split('/')
            ae(db_path, fs_path)
            ae(initial_side_data, side_data(book_id))

        # test only formats being changed
        init_cache()
        ef = set()
        for efx in cache.list_extra_files(1):
            ef.add(efx.relpath)
            self.assertTrue(os.path.exists(efx.file_path))
        self.assertEqual(ef, {'a.side', 'subdir/a.fmt1'})
        fname = cache.fields['formats'].table.fname_map[1]['FMT1']
        cache.fields['formats'].table.fname_map[1]['FMT1'] = 'some thing else'
        cache.fields['formats'].table.fname_map[1]['FMT2'] = fname.upper()
        cache.backend.update_path(1, cache.field_for('title', 1), cache.field_for('authors', 1)[0], cache.fields['path'], cache.fields['formats'])
        check_that_filesystem_and_db_entries_match(1)

        # test a case only change
        init_cache()
        title = cache.field_for('title', 1)
        self.assertNotEqual(title, title.upper())
        cache.set_field('title', {1: title.upper()})
        check_that_filesystem_and_db_entries_match(1)

        # test a title change
        init_cache()
        cache.set_field('title', {1: 'new changed title'})
        check_that_filesystem_and_db_entries_match(1)
        # test an author change
        cache.set_field('authors', {1: ('new changed author',)})
        check_that_filesystem_and_db_entries_match(1)
        # test a double change
        from calibre.ebooks.metadata.book.base import Metadata
        cache.set_metadata(1, Metadata('t1', ('a1', 'a2')))
        check_that_filesystem_and_db_entries_match(1)
        # check that empty author folders are removed
        for x in os.scandir(cache.backend.library_path):
            if x.is_dir():
                self.assertTrue(os.listdir(x.path))

    def test_rename_of_extra_files(self):
        cl = self.cloned_library
        cache = self.init_cache(cl)
        cache.add_extra_files(1, {'a': BytesIO(b'aaa'), 'b': BytesIO(b'bbb')})

        def relpaths():
            return {e.relpath for e in cache.list_extra_files(1)}

        self.assertEqual(relpaths(), {'a', 'b'})
        self.assertEqual(cache.rename_extra_files(1, {'a': 'data/c'}), {'a'})
        self.assertEqual(relpaths(), {'data/c', 'b'})
        self.assertEqual(cache.rename_extra_files(1, {'b': 'B'}), {'b'})
        self.assertEqual(relpaths(), {'data/c', 'B'})
        self.assertEqual(cache.rename_extra_files(1, {'B': 'data/c'}), set())
        self.assertEqual(cache.rename_extra_files(1, {'B': 'data/c'}, replace=True), {'B'})

    @unittest.skipUnless(iswindows, 'Windows only')
    def test_windows_atomic_move(self):
        'Test book file open in another process when changing metadata'
        cl = self.cloned_library
        cache = self.init_cache(cl)
        fpath = cache.format_abspath(1, 'FMT1')
        with open(fpath, 'rb') as f:
            with self.assertRaises(IOError):
                cache.set_field('title', {1:'Moved'})
            with self.assertRaises(IOError):
                cache.remove_books({1})
        self.assertNotEqual(cache.field_for('title', 1), 'Moved', 'Title was changed despite file lock')

        # Test on folder with hardlinks
        from calibre.ptempfile import TemporaryDirectory
        from calibre.utils.filenames import WindowsAtomicFolderMove, hardlink_file
        raw = b'xxx'
        with TemporaryDirectory() as tdir1, TemporaryDirectory() as tdir2:
            a, b = os.path.join(tdir1, 'a'), os.path.join(tdir1, 'b')
            a = os.path.join(tdir1, 'a')
            with open(a, 'wb') as f:
                f.write(raw)
            hardlink_file(a, b)
            wam = WindowsAtomicFolderMove(tdir1)
            wam.copy_path_to(a, os.path.join(tdir2, 'a'))
            wam.copy_path_to(b, os.path.join(tdir2, 'b'))
            wam.delete_originals()
            self.assertEqual([], os.listdir(tdir1))
            self.assertEqual({'a', 'b'}, set(os.listdir(tdir2)))
            self.assertEqual(raw, read(os.path.join(tdir2, 'a'), 'rb'))
            self.assertEqual(raw, read(os.path.join(tdir2, 'b'), 'rb'))

    def test_library_move(self):
        ' Test moving of library '
        from calibre.ptempfile import TemporaryDirectory
        cache = self.init_cache()
        self.assertIn('metadata.db', cache.get_top_level_move_items()[0])
        all_ids = cache.all_book_ids()
        fmt1 = cache.format(1, 'FMT1')
        cov = cache.cover(1)
        odir = cache.backend.library_path
        with TemporaryDirectory('moved_lib') as tdir:
            cache.move_library_to(tdir)
            self.assertIn('moved_lib', cache.backend.library_path)
            self.assertIn('moved_lib', cache.backend.dbpath)
            self.assertEqual(fmt1, cache.format(1, 'FMT1'))
            self.assertEqual(cov, cache.cover(1))
            cache.reload_from_db()
            self.assertEqual(all_ids, cache.all_book_ids())
            cache.backend.close()
            self.assertFalse(os.path.exists(odir))
            os.mkdir(odir)  # needed otherwise tearDown() fails

    def test_long_filenames(self):
        ' Test long file names '
        cache = self.init_cache()
        cache.set_field('title', {1:'a'*10000})
        self.assertLessEqual(len(cache.field_for('path', 1)), cache.backend.PATH_LIMIT * 2)
        cache.set_field('authors', {1:'b'*10000})
        self.assertLessEqual(len(cache.field_for('path', 1)), cache.backend.PATH_LIMIT * 2)
        fpath = cache.format_abspath(1, cache.formats(1)[0])
        self.assertLessEqual(len(fpath), len(cache.backend.library_path) + cache.backend.PATH_LIMIT * 4)

    def test_reserved_names(self):
        ' Test that folders are not created with a windows reserve name '
        cache = self.init_cache()
        cache.set_field('authors', {1:'con'})
        p = cache.field_for('path', 1).replace(os.sep, '/').split('/')
        self.assertNotIn('con', p)

    def test_fname_change(self):
        ' Test the changing of the filename but not the folder name '
        cache = self.init_cache()
        title = 'a'*30 + 'bbb'
        cache.backend.PATH_LIMIT = 100
        cache.set_field('title', {3:title})
        cache.add_format(3, 'TXT', BytesIO(b'xxx'))
        cache.backend.PATH_LIMIT = 40
        cache.set_field('title', {3:title})
        fpath = cache.format_abspath(3, 'TXT')
        self.assertEqual(sorted([os.path.basename(fpath)]), sorted(os.listdir(os.path.dirname(fpath))))

    def test_export_import(self):
        from calibre.db.cache import import_library
        from calibre.utils.exim import Exporter, Importer
        with TemporaryDirectory('export_lib') as tdir:
            for part_size in (8, 1, 1024):
                exporter = Exporter(tdir, part_size=part_size + Exporter.tail_size())
                files = {
                    'a': b'a' * 7, 'b': b'b' * 7, 'c': b'c' * 2, 'd': b'd' * 9, 'e': b'e' * 3,
                }
                for key, data in files.items():
                    exporter.add_file(BytesIO(data), key)
                exporter.commit()
                importer = Importer(tdir)
                for key, expected in files.items():
                    with importer.start_file(key, key) as f:
                        actual = f.read()
                    self.assertEqual(expected, actual, key)
                self.assertFalse(importer.corrupted_files)
        cache = self.init_cache()
        bookdir = os.path.dirname(cache.format_abspath(1, '__COVER_INTERNAL__'))
        with open(os.path.join(bookdir, 'exf'), 'w') as f:
            f.write('exf')
        os.mkdir(os.path.join(bookdir, 'sub'))
        with open(os.path.join(bookdir, 'sub', 'recurse'), 'w') as f:
            f.write('recurse')
        self.assertEqual({ef.relpath for ef in cache.list_extra_files(1, pattern='sub/**/*')}, {'sub/recurse'})
        self.assertEqual({ef.relpath for ef in cache.list_extra_files(1)}, {'exf', 'sub/recurse'})
        for part_size in (512, 1027, None):
            with TemporaryDirectory('export_lib') as tdir, TemporaryDirectory('import_lib') as idir:
                exporter = Exporter(tdir, part_size=part_size if part_size is None else (part_size + Exporter.tail_size()))
                cache.export_library('l', exporter)
                exporter.commit()
                importer = Importer(tdir)
                ic = import_library('l', importer, idir)
                self.assertFalse(importer.corrupted_files)
                self.assertEqual(cache.all_book_ids(), ic.all_book_ids())
                for book_id in cache.all_book_ids():
                    self.assertEqual(cache.cover(book_id), ic.cover(book_id), f'Covers not identical for book: {book_id}')
                    for fmt in cache.formats(book_id):
                        self.assertEqual(cache.format(book_id, fmt), ic.format(book_id, fmt))
                        self.assertEqual(cache.format_metadata(book_id, fmt)['mtime'], cache.format_metadata(book_id, fmt)['mtime'])
                bookdir = os.path.dirname(ic.format_abspath(1, '__COVER_INTERNAL__'))
                self.assertEqual('exf', read(os.path.join(bookdir, 'exf')))
                self.assertEqual('recurse', read(os.path.join(bookdir, 'sub', 'recurse')))
        r1 = cache.add_notes_resource(b'res1', 'res.jpg', mtime=time.time()-113)
        r2 = cache.add_notes_resource(b'res2', 'res.jpg', mtime=time.time()-1115)
        cache.set_notes_for('authors', 2, 'some notes', resource_hashes=(r1, r2))
        cache.add_format(1, 'TXT', BytesIO(b'testing exim'))
        cache.fts_indexing_sleep_time = 0.001
        cache.enable_fts()
        cache.set_fts_num_of_workers(4)
        st = time.monotonic()
        while cache.fts_indexing_left > 0 and time.monotonic() - st < 15:
            time.sleep(0.05)
        if cache.fts_indexing_left > 0:
            raise ValueError('FTS indexing did not complete')
        self.assertEqual(cache.fts_search('exim')[0]['id'], 1)
        with TemporaryDirectory('export_lib') as tdir, TemporaryDirectory('import_lib') as idir:
            exporter = Exporter(tdir)
            cache.export_library('l', exporter)
            exporter.commit()
            importer = Importer(tdir)
            ic = import_library('l', importer, idir)
            self.assertFalse(importer.corrupted_files)
            self.assertEqual(ic.fts_search('exim')[0]['id'], 1)
            self.assertEqual(cache.notes_for('authors', 2), ic.notes_for('authors', 2))
            a, b = cache.get_notes_resource(r1), ic.get_notes_resource(r1)
            at, bt, = a.pop('mtime'), b.pop('mtime')
            self.assertEqual(a, b)
            self.assertLess(abs(at-bt), 2)

    def test_find_books_in_directory(self):
        from calibre.db.adding import compile_rule, find_books_in_directory
        def strip(files):
            return frozenset({os.path.basename(x) for x in files})

        def q(one, two):
            one, two = {strip(a) for a in one}, {strip(b) for b in two}
            self.assertEqual(one, two)

        def r(action='ignore', match_type='startswith', query=''):
            return {'action':action, 'match_type':match_type, 'query':query}

        def c(*rules):
            return tuple(map(compile_rule, rules))

        files = ['added.epub', 'ignored.md', 'non-book.other']
        q(['added.epub ignored.md'.split()], find_books_in_directory('', True, listdir_impl=lambda x: files))
        q([['added.epub'], ['ignored.md']], find_books_in_directory('', False, listdir_impl=lambda x, **k: files))
        for rules in (
                c(r(query='ignored.'), r(action='add', match_type='endswith', query='.OTHER')),
                c(r(match_type='glob', query='*.md'), r(action='add', match_type='matches', query=r'.+\.other$')),
                c(r(match_type='not_startswith', query='IGnored.', action='add'), r(query='ignored.md')),
        ):
            q(['added.epub non-book.other'.split()], find_books_in_directory('', True, compiled_rules=rules, listdir_impl=lambda x: files))
