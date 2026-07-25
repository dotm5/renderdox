/******************************************************************************
 * The MIT License (MIT)
 *
 * Copyright (c) 2026
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 ******************************************************************************/

#pragma once

#include <functional>
#include <QByteArray>
#include <QJsonObject>
#include <QJsonValue>
#include <QModelIndex>
#include <QSet>
#include <QString>
#include <QVariant>
#include <QVector>

class QAbstractItemView;
class QAbstractItemModel;
class QIODevice;
class QObject;

enum class StructuredTableFormat
{
  TSV,
  CSV,
  JSON,
};

struct StructuredTableMetadata
{
  uint32_t schemaVersion = 1;
  QString captureSHA256;
  QString capturePath;
  QString api;
  QString renderDocVersion;
  QString portCommit;
  QString generatedAt;
  uint32_t eventId = 0;
};

struct StructuredTableOptions
{
  bool includeHeaders = true;
  bool includeMetadata = true;
};

class StructuredTableExport
{
public:
  // Progress receives completed and total cell counts. Returning false cancels the operation.
  typedef std::function<bool(quint64, quint64)> ProgressCallback;
  typedef std::function<void(bool, const QString &)> CompletionCallback;

  static bool HasExportableSelection(QAbstractItemView *view);

  static QByteArray Encode(QAbstractItemView *view, StructuredTableFormat format,
                           const StructuredTableMetadata &metadata,
                           const StructuredTableOptions &options, QString *error = NULL,
                           ProgressCallback progress = ProgressCallback());

  // Model overloads keep the serialization core testable and usable without a GUI event loop.
  // Rows and columns are model coordinates in the requested output order.
  static QByteArray EncodeModel(QAbstractItemModel *model, const QVector<int> &rows,
                                const QVector<int> &columns, StructuredTableFormat format,
                                const StructuredTableMetadata &metadata,
                                const StructuredTableOptions &options, QString *error = NULL,
                                ProgressCallback progress = ProgressCallback());

  static bool Save(QAbstractItemView *view, StructuredTableFormat format, const QString &filename,
                   const StructuredTableMetadata &metadata, const StructuredTableOptions &options,
                   QString *error = NULL, ProgressCallback progress = ProgressCallback());

  // Writes bounded chunks on successive GUI event-loop turns. The model stays on its owning
  // thread, while QSaveFile guarantees that cancellation or failure never publishes a partial
  // destination file.
  static void SaveAsync(QAbstractItemView *view, StructuredTableFormat format,
                        const QString &filename, const StructuredTableMetadata &metadata,
                        const StructuredTableOptions &options, QObject *context,
                        CompletionCallback completion,
                        ProgressCallback progress = ProgressCallback());

  static bool SaveModel(QAbstractItemModel *model, const QVector<int> &rows,
                        const QVector<int> &columns, StructuredTableFormat format,
                        const QString &filename, const StructuredTableMetadata &metadata,
                        const StructuredTableOptions &options, QString *error = NULL,
                        ProgressCallback progress = ProgressCallback());

  static bool CopyTSV(QAbstractItemView *view, const StructuredTableMetadata &metadata,
                      bool includeHeaders, QString *error = NULL);

  static QByteArray EncodeDelimitedField(const QString &text, char delimiter);
  static QJsonObject MetadataObject(const StructuredTableMetadata &metadata);

private:
  struct Selection
  {
    QVector<QPersistentModelIndex> rows;
    QVector<int> columns;
    // Empty for row/column selections where every output cell is selected.
    QSet<QPersistentModelIndex> selectedCells;
    bool rectangular = true;
  };

  static bool BuildSelection(QAbstractItemView *view, Selection &selection, QString *error);
  static bool Write(QAbstractItemView *view, QIODevice &device, StructuredTableFormat format,
                    const StructuredTableMetadata &metadata,
                    const StructuredTableOptions &options, QString *error,
                    ProgressCallback progress);
  static bool WriteModel(QAbstractItemModel *model, const Selection &selection, QIODevice &device,
                         StructuredTableFormat format,
                         const StructuredTableMetadata &metadata,
                         const StructuredTableOptions &options, QString *error,
                         ProgressCallback progress);
  static bool CellSelected(const Selection &selection, const QModelIndex &index);
  static QVariant RawValue(const QModelIndex &index);
  static QJsonObject CellObject(const QModelIndex &index);
  static QJsonValue RawJsonValue(const QVariant &value, QString &typeName);
};
