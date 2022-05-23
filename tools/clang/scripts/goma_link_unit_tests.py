#! /usr/bin/env python3
# Copyright (c) 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Unit tests for goma_link.
#
# Usage:
#
#   tools/clang/scripts/goma_link_unit_tests.py
#
# A coverage report combining these tests with the integration tests
# in goma_link_integration_tests.py can be generated by running:
#
#   env COVERAGE_FILE=.coverage.unit python3 third_party/pycoverage run \
#     tools/clang/scripts/goma_link_unit_tests.py
#   env COVERAGE_FILE=.coverage.integration python3 third_party/pycoverage \
#     run tools/clang/scripts/goma_link_integration_tests.py
#   python3 third_party/pycoverage combine
#   python3 third_party/pycoverage html
#
# The report will be available as htmlcov/index.html

import goma_ld
import goma_link

import os
import unittest
from unittest import mock

from goma_link_test_utils import named_directory, working_directory


class FakeFs(object):
  """
  Context manager that mocks the functions through which goma_link
  interacts with the filesystem.
  """

  def __init__(self, bitcode_files=None, other_files=None):
    self.bitcode_files = set(bitcode_files or [])
    self.other_files = set(other_files or [])

    def ensure_file(path):
      self.other_files.add(path)

    def exists(path):
      return path in self.bitcode_files or path in self.other_files

    def is_bitcode_file(path):
      return path in self.bitcode_files

    self.mock_ensure_file = mock.patch('goma_link.ensure_file', ensure_file)
    self.mock_exists = mock.patch('os.path.exists', exists)
    self.mock_is_bitcode_file = mock.patch('goma_link.is_bitcode_file',
                                           is_bitcode_file)

  def __enter__(self):
    self.mock_ensure_file.start()
    self.mock_exists.start()
    self.mock_is_bitcode_file.start()
    return self

  def __exit__(self, exnty, *args, **kwargs):
    self.mock_is_bitcode_file.stop()
    self.mock_exists.stop()
    self.mock_ensure_file.stop()
    return exnty is None


class GomaLinkUnitTest(unittest.TestCase):
  """
  Unit tests for goma_link.
  """

  def test_analyze_expanded_args_nocodegen(self):
    with FakeFs(other_files=['foo.o', 'bar.o']):
      self.assertIsNone(goma_ld.GomaLinkUnix().analyze_expanded_args(
          ['clang', 'foo.o', 'bar.o', '-o', 'foo'], 'foo', 'clang', 'lto.foo',
          'common', False))

  def test_analyze_expanded_args_one_codegen(self):
    with FakeFs(bitcode_files=['foo.o'], other_files=['bar.o']):
      result = goma_ld.GomaLinkUnix().analyze_expanded_args(
          ['clang', 'foo.o', 'bar.o', '-o', 'foo'], 'foo', 'clang', 'lto.foo',
          'common', False)
      self.assertIsNotNone(result)
      self.assertNotEqual(len(result.codegen), 0)
      self.assertEqual(result.codegen[0][1], 'foo.o')
      self.assertEqual(len(result.codegen), 1)
      self.assertIn('foo.o', result.index_params)
      self.assertIn('bar.o', result.index_params)
      self.assertIn('bar.o', result.final_params)
      # foo.o should not be in final_params because it will be added via
      # the used object file.
      self.assertNotIn('foo.o', result.final_params)

  def test_analyze_expanded_args_params(self):
    with FakeFs(bitcode_files=['foo.o']):
      result = goma_ld.GomaLinkUnix().analyze_expanded_args([
          'clang', '-O2', '-flto=thin', '-fsplit-lto-unit',
          '-fwhole-program-vtables', '-fsanitize=cfi', '-g', '-gsplit-dwarf',
          '-mllvm', '-generate-type-units', 'foo.o', '-o', 'foo'
      ], 'foo', 'clang', 'lto.foo', 'common', False)
      self.assertIsNotNone(result)
      self.assertIn('-Wl,-plugin-opt=obj-path=lto.foo/foo.split.o',
                    result.index_params)
      self.assertIn('-O2', result.index_params)
      self.assertIn('-g', result.index_params)
      self.assertIn('-gsplit-dwarf', result.index_params)
      self.assertIn('-mllvm -generate-type-units',
                    ' '.join(result.index_params))
      self.assertIn('-flto=thin', result.index_params)
      self.assertIn('-fwhole-program-vtables', result.index_params)
      self.assertIn('-fsanitize=cfi', result.index_params)

      self.assertIn('-O2', result.codegen_params)
      self.assertIn('-g', result.codegen_params)
      self.assertIn('-gsplit-dwarf', result.codegen_params)
      self.assertIn('-mllvm -generate-type-units',
                    ' '.join(result.codegen_params))
      self.assertNotIn('-flto=thin', result.codegen_params)
      self.assertNotIn('-fwhole-program-vtables', result.codegen_params)
      self.assertNotIn('-fsanitize=cfi', result.codegen_params)

      self.assertIn('-flto=thin', result.final_params)

  def test_codegen_params_default(self):
    with FakeFs(bitcode_files=['foo.o'], other_files=['bar.o']):
      result = goma_ld.GomaLinkUnix().analyze_expanded_args(
          ['clang', 'foo.o', 'bar.o', '-o', 'foo'], 'foo', 'clang', 'lto.foo',
          'common', False)
      # Codegen optimization level should default to 2.
      self.assertIn('-O2', result.codegen_params)
      # -fdata-sections and -ffunction-sections default to on to match the
      # behavior of local linking.
      self.assertIn('-fdata-sections', result.codegen_params)
      self.assertIn('-ffunction-sections', result.codegen_params)

  def test_codegen_params_default_cl(self):
    with FakeFs(bitcode_files=['foo.obj'], other_files=['bar.obj']):
      result = goma_link.GomaLinkWindows().analyze_expanded_args(
          ['clang-cl', 'foo.obj', 'bar.obj', '-Fefoo.exe'], 'foo.exe',
          'clang-cl', 'lto.foo', 'common', False)
      # Codegen optimization level should default to 2.
      self.assertIn('-O2', result.codegen_params)
      # -Gw and -Gy default to on to match the behavior of local linking.
      self.assertIn('-Gw', result.codegen_params)
      self.assertIn('-Gy', result.codegen_params)

  def test_codegen_params_no_data_sections(self):
    with FakeFs(bitcode_files=['foo.o'], other_files=['bar.o']):
      result = goma_ld.GomaLinkUnix().analyze_expanded_args(
          ['clang', '-fno-data-sections', 'foo.o', 'bar.o', '-o', 'foo'], 'foo',
          'clang', 'lto.foo', 'common', False)
      self.assertNotIn('-fdata-sections', result.codegen_params)
      self.assertIn('-ffunction-sections', result.codegen_params)

  def test_codegen_params_no_function_sections(self):
    with FakeFs(bitcode_files=['foo.o'], other_files=['bar.o']):
      result = goma_ld.GomaLinkUnix().analyze_expanded_args(
          ['clang', '-fno-function-sections', 'foo.o', 'bar.o', '-o', 'foo'],
          'foo', 'clang', 'lto.foo', 'common', False)
      self.assertIn('-fdata-sections', result.codegen_params)
      self.assertNotIn('-ffunction-sections', result.codegen_params)

  def test_codegen_params_no_data_sections_cl(self):
    with FakeFs(bitcode_files=['foo.obj'], other_files=['bar.obj']):
      result = goma_link.GomaLinkWindows().analyze_expanded_args(
          ['clang-cl', '/Gw-', 'foo.obj', 'bar.obj', '/Fefoo.exe'], 'foo.exe',
          'clang-cl', 'lto.foo', 'common', False)
      self.assertNotIn('-fdata-sections', result.codegen_params)
      self.assertNotIn('-Gw', result.codegen_params)
      self.assertNotIn('/Gw', result.codegen_params)
      self.assertIn('-Gy', result.codegen_params)

  def test_codegen_params_no_function_sections_cl(self):
    with FakeFs(bitcode_files=['foo.obj'], other_files=['bar.obj']):
      result = goma_link.GomaLinkWindows().analyze_expanded_args(
          ['clang-cl', '/Gy-', 'foo.obj', 'bar.obj', '/Fefoo.exe'], 'foo.exe',
          'clang-cl', 'lto.foo', 'common', False)
      self.assertIn('-Gw', result.codegen_params)
      self.assertNotIn('-ffunction-sections', result.codegen_params)
      self.assertNotIn('-Gy', result.codegen_params)
      self.assertNotIn('/Gy', result.codegen_params)

  def test_codegen_params_explicit_data_and_function_sections(self):
    with FakeFs(bitcode_files=['foo.o'], other_files=['bar.o']):
      result = goma_ld.GomaLinkUnix().analyze_expanded_args([
          'clang', '-ffunction-sections', '-fdata-sections', 'foo.o', 'bar.o',
          '-o', 'foo'
      ], 'foo', 'clang', 'lto.foo', 'common', False)
      self.assertIn('-fdata-sections', result.codegen_params)
      self.assertIn('-ffunction-sections', result.codegen_params)

  def test_codegen_params_explicit_data_and_function_sections_cl(self):
    with FakeFs(bitcode_files=['foo.obj'], other_files=['bar.obj']):
      result = goma_link.GomaLinkWindows().analyze_expanded_args(
          ['clang-cl', '/Gy', '-Gw', 'foo.obj', 'bar.obj', '/Fefoo.exe'],
          'foo.exe', 'clang-cl', 'lto.foo', 'common', False)
      self.assertIn('-Gw', result.codegen_params)
      self.assertIn('/Gy', result.codegen_params)
      self.assertNotIn('-fdata-sections', result.codegen_params)
      self.assertNotIn('-ffunction-sections', result.codegen_params)

  def test_ensure_file_no_dir(self):
    with named_directory() as d, working_directory(d):
      self.assertFalse(os.path.exists('test'))
      goma_link.ensure_file('test')
      self.assertTrue(os.path.exists('test'))

  def test_ensure_file_existing(self):
    with named_directory() as d, working_directory(d):
      self.assertFalse(os.path.exists('foo/test'))
      goma_link.ensure_file('foo/test')
      self.assertTrue(os.path.exists('foo/test'))
      os.utime('foo/test', (0, 0))
      statresult = os.stat('foo/test')
      goma_link.ensure_file('foo/test')
      self.assertTrue(os.path.exists('foo/test'))
      newstatresult = os.stat('foo/test')
      self.assertEqual(newstatresult.st_mtime, statresult.st_mtime)

  def test_ensure_file_error(self):
    with named_directory() as d, working_directory(d):
      self.assertFalse(os.path.exists('test'))
      goma_link.ensure_file('test')
      self.assertTrue(os.path.exists('test'))
      self.assertRaises(OSError, goma_link.ensure_file, 'test/impossible')

  def test_transform_codegen_param_on_mllvm(self):
    # Regression test for crbug.com/1135234
    link = goma_ld.GomaLinkUnix()
    self.assertEqual(
        link.transform_codegen_param_common('-mllvm,-import-instr-limit=20'),
        ['-mllvm', '-import-instr-limit=20'])


if __name__ == '__main__':
  unittest.main()