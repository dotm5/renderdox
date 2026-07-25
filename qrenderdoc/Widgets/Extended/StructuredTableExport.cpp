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

#include "StructuredTableExport.h"
#include <algorithm>
#include <memory>
#include <QAbstractItemModel>
#include <QAbstractItemView>
#include <QApplication>
#include <QBuffer>
#include <QClipboard>
#include <QFile>
#include <QHeaderView>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonValue>
#include <QPointer>
#include <QSaveFile>
#include <QSet>
#include <QTableView>
#include <QTimer>
#include <QTreeView>
#include "resourceid.h"

namespace
{
QVector<int> VisibleColumns(QAbstractItemView *view)
{
  QVector<int> columns;
  QAbstractItemModel *model = view ? view->model() : NULL;
  if(model == NULL)
    return columns;

  QHeaderView *header = NULL;
  if(QTableView *table = qobject_cast<QTableView *>(view))
    header = table->horizontalHeader();
  else if(QTreeView *tree = qobject_cast<QTreeView *>(view))
    header = tree->header();

  if(header)
  {
    for(int visual = 0; visual < header->count(); visual++)
    {
      int logical = header->logicalIndex(visual);
      if(logical >= 0 && !header->isSectionHidden(logical))
        columns.push_back(logical);
    }
  }
  else
  {
    for(int column = 0; column < model->columnCount(); column++)
      columns.push_back(column);
  }

  return columns;
}

void SortUnique(QVector<int> &values)
{
  std::sort(values.begin(), values.end());
  values.erase(std::unique(values.begin(), values.end()), values.end());
}

bool WriteBytes(QIODevice &device, const QByteArray &bytes, QString *error)
{
  if(device.write(bytes) != bytes.size())
  {
    if(error)
      *error = device.errorString();
    return false;
  }
  return true;
}

QByteArray Json(const QJsonValue &value)
{
  if(value.isObject())
    return QJsonDocument(value.toObject()).toJson(QJsonDocument::Compact);
  if(value.isArray())
    return QJsonDocument(value.toArray()).toJson(QJsonDocument::Compact);

  QJsonArray wrapper;
  wrapper.append(value);
  QByteArray bytes = QJsonDocument(wrapper).toJson(QJsonDocument::Compact);
  return bytes.mid(1, bytes.size() - 2);
}

QByteArray MetadataDelimited(const StructuredTableMetadata &metadata, char delimiter,
                             const QByteArray &newline)
{
  const QJsonObject object = StructuredTableExport::MetadataObject(metadata);
  const QStringList keys = {
      lit("schemaVersion"), lit("captureSHA256"), lit("capturePath"), lit("api"),
      lit("renderDocVersion"), lit("portCommit"), lit("generatedAt"), lit("eventId"),
  };

  QByteArray ret;
  for(const QString &key : keys)
  {
    ret += StructuredTableExport::EncodeDelimitedField(lit("__metadata__"), delimiter);
    ret += delimiter;
    ret += StructuredTableExport::EncodeDelimitedField(key, delimiter);
    ret += delimiter;
    ret += StructuredTableExport::EncodeDelimitedField(object[key].toVariant().toString(), delimiter);
    ret += newline;
  }
  ret += StructuredTableExport::EncodeDelimitedField(lit("__table__"), delimiter);
  ret += newline;
  return ret;
}
}    // namespace

bool StructuredTableExport::CellSelected(const Selection &selection, const QModelIndex &index)
{
  return selection.rectangular || selection.selectedCells.contains(QPersistentModelIndex(index));
}

bool StructuredTableExport::HasExportableSelection(QAbstractItemView *view)
{
  return view && view->model() && view->selectionModel() &&
         (!view->selectionModel()->selectedIndexes().isEmpty() || view->currentIndex().isValid());
}

bool StructuredTableExport::BuildSelection(QAbstractItemView *view, Selection &selection,
                                           QString *error)
{
  if(view == NULL || view->model() == NULL || view->selectionModel() == NULL)
  {
    if(error)
      *error = lit("The focused widget is not an exportable item view.");
    return false;
  }

  const QAbstractItemView::SelectionBehavior behavior = view->selectionBehavior();
  QModelIndexList indices = view->selectionModel()->selectedIndexes();
  if(indices.isEmpty() && view->currentIndex().isValid())
    indices.push_back(view->currentIndex());

  if(indices.isEmpty())
  {
    if(error)
      *error = lit("The focused table has no selected cell or row.");
    return false;
  }

  const QVector<int> visibleColumns = VisibleColumns(view);
  if(visibleColumns.isEmpty())
  {
    if(error)
      *error = lit("The selection contains no visible columns.");
    return false;
  }

  QSet<int> visibleSet;
  for(int column : visibleColumns)
    visibleSet.insert(column);

  if(behavior == QAbstractItemView::SelectRows)
  {
    QSet<QPersistentModelIndex> seenRows;
    for(const QModelIndex &index : indices)
    {
      QModelIndex representative = index.sibling(index.row(), visibleColumns[0]);
      QPersistentModelIndex persistent(representative);
      if(!seenRows.contains(persistent))
      {
        seenRows.insert(persistent);
        selection.rows.push_back(persistent);
      }
    }
    selection.columns = visibleColumns;
    selection.rectangular = true;
  }
  else if(behavior == QAbstractItemView::SelectColumns)
  {
    for(const QModelIndex &index : indices)
    {
      if(visibleSet.contains(index.column()))
        selection.columns.push_back(index.column());
    }
    SortUnique(selection.columns);
    if(QTreeView *tree = qobject_cast<QTreeView *>(view))
    {
      QModelIndex index = view->model()->index(0, selection.columns[0]);
      while(index.isValid())
      {
        selection.rows.push_back(QPersistentModelIndex(index));
        index = tree->indexBelow(index);
      }
    }
    else
    {
      for(int row = 0; row < view->model()->rowCount(); row++)
        selection.rows.push_back(QPersistentModelIndex(view->model()->index(row, 0)));
    }
    selection.rectangular = true;
  }
  else
  {
    selection.rectangular = false;
    QSet<QPersistentModelIndex> seenRows;
    for(const QModelIndex &index : indices)
    {
      if(!visibleSet.contains(index.column()))
        continue;
      QPersistentModelIndex representative(index.sibling(index.row(), visibleColumns[0]));
      if(!seenRows.contains(representative))
      {
        seenRows.insert(representative);
        selection.rows.push_back(representative);
      }
      selection.columns.push_back(index.column());
      selection.selectedCells.insert(QPersistentModelIndex(index));
    }

    // Preserve the current visual column order rather than sorting by logical index.
    QSet<int> selectedColumns;
    for(int column : selection.columns)
      selectedColumns.insert(column);
    selection.columns.clear();
    for(int column : visibleColumns)
    {
      if(selectedColumns.contains(column))
        selection.columns.push_back(column);
    }
  }

  if(selection.rows.isEmpty() || selection.columns.isEmpty())
  {
    if(error)
      *error = lit("The selection contains no visible cells.");
    return false;
  }

  return true;
}

QVariant StructuredTableExport::RawValue(const QModelIndex &index)
{
  QVariant raw = index.data(Qt::EditRole);
  if(!raw.isValid())
    raw = index.data(Qt::DisplayRole);
  return raw;
}

QJsonValue StructuredTableExport::RawJsonValue(const QVariant &value, QString &typeName)
{
  if(!value.isValid() || value.isNull())
  {
    typeName = lit("null");
    return QJsonValue(QJsonValue::Null);
  }

  if(value.userType() == QMetaType::Float)
  {
    typeName = lit("float32");
    return QJsonValue(double(value.toFloat()));
  }

  if(value.userType() == qMetaTypeId<ResourceId>())
  {
    typeName = lit("ResourceId");
    return QJsonValue(ToQStr(value.value<ResourceId>()));
  }

  switch(value.type())
  {
    case QVariant::Bool:
      typeName = lit("bool");
      return QJsonValue(value.toBool());
    case QVariant::Int:
      typeName = lit("int32");
      return QJsonValue(value.toInt());
    case QVariant::UInt:
      typeName = lit("uint32");
      return QJsonValue(qint64(value.toUInt()));
    case QVariant::LongLong:
      // JSON numbers cannot represent every signed 64-bit integer exactly.
      typeName = lit("int64-string");
      return QJsonValue(QString::number(value.toLongLong()));
    case QVariant::ULongLong:
      typeName = lit("uint64-string");
      return QJsonValue(QString::number(value.toULongLong()));
    case QVariant::Double:
      typeName = lit("float64");
      return QJsonValue(value.toDouble());
    case QVariant::String:
      typeName = lit("string");
      return QJsonValue(value.toString());
    default:
      typeName = QString::fromLatin1(value.typeName() ? value.typeName() : "display-only");
      return QJsonValue(value.toString());
  }
}

QJsonObject StructuredTableExport::CellObject(const QModelIndex &index)
{
  QJsonObject cell;
  QVariant raw = RawValue(index);
  QString rawType;
  cell[lit("raw")] = RawJsonValue(raw, rawType);
  cell[lit("rawType")] = rawType;
  cell[lit("display")] = index.data(Qt::DisplayRole).toString();
  return cell;
}

QJsonObject StructuredTableExport::MetadataObject(const StructuredTableMetadata &metadata)
{
  QJsonObject object;
  object[lit("schemaVersion")] = int(metadata.schemaVersion);
  object[lit("captureSHA256")] = metadata.captureSHA256;
  object[lit("capturePath")] = metadata.capturePath;
  object[lit("api")] = metadata.api;
  object[lit("renderDocVersion")] = metadata.renderDocVersion;
  object[lit("portCommit")] = metadata.portCommit;
  object[lit("generatedAt")] = metadata.generatedAt;
  object[lit("eventId")] = int(metadata.eventId);
  return object;
}

QByteArray StructuredTableExport::EncodeDelimitedField(const QString &text, char delimiter)
{
  QString escaped = text;
  bool quote = escaped.contains(QLatin1Char(delimiter)) || escaped.contains(QLatin1Char('"')) ||
               escaped.contains(QLatin1Char('\r')) || escaped.contains(QLatin1Char('\n'));
  escaped.replace(lit("\""), lit("\"\""));
  QByteArray bytes = escaped.toUtf8();
  if(quote)
    bytes = QByteArray("\"") + bytes + QByteArray("\"");
  return bytes;
}

bool StructuredTableExport::Write(QAbstractItemView *view, QIODevice &device,
                                  StructuredTableFormat format,
                                  const StructuredTableMetadata &metadata,
                                  const StructuredTableOptions &options, QString *error,
                                  ProgressCallback progress)
{
  Selection selection;
  if(!BuildSelection(view, selection, error))
    return false;

  return WriteModel(view->model(), selection, device, format, metadata, options, error, progress);
}

bool StructuredTableExport::WriteModel(QAbstractItemModel *model, const Selection &selection,
                                       QIODevice &device, StructuredTableFormat format,
                                       const StructuredTableMetadata &metadata,
                                       const StructuredTableOptions &options, QString *error,
                                       ProgressCallback progress)
{
  if(model == NULL || selection.rows.isEmpty() || selection.columns.isEmpty())
  {
    if(error)
      *error = lit("The table selection contains no exportable cells.");
    return false;
  }

  const quint64 total = quint64(selection.rows.size()) * quint64(selection.columns.size());
  quint64 completed = 0;

  auto advance = [&]() {
    completed++;
    if(progress && (completed == total || (completed % 4096) == 0))
      return progress(completed, total);
    return true;
  };

  if(format == StructuredTableFormat::JSON)
  {
    if(!WriteBytes(device, QByteArray("{\"metadata\":"), error) ||
       !WriteBytes(device, Json(MetadataObject(metadata)), error) ||
       !WriteBytes(device, QByteArray(",\"columns\":["), error))
      return false;

    for(int colIndex = 0; colIndex < selection.columns.size(); colIndex++)
    {
      if(colIndex > 0 && !WriteBytes(device, QByteArray(","), error))
        return false;
      int column = selection.columns[colIndex];
      QJsonObject columnObject;
      columnObject[lit("modelColumn")] = column;
      columnObject[lit("display")] =
          model->headerData(column, Qt::Horizontal, Qt::DisplayRole).toString();
      if(!WriteBytes(device, Json(columnObject), error))
        return false;
    }

    if(!WriteBytes(device, QByteArray("],\"rows\":["), error))
      return false;

    for(int rowIndex = 0; rowIndex < selection.rows.size(); rowIndex++)
    {
      if(rowIndex > 0 && !WriteBytes(device, QByteArray(","), error))
        return false;

      QModelIndex rowIndexModel = selection.rows[rowIndex];
      QJsonArray modelPath;
      for(QModelIndex path = rowIndexModel; path.isValid(); path = path.parent())
        modelPath.prepend(path.row());

      QByteArray rowPrefix = QByteArray("{\"modelRow\":") +
                             QByteArray::number(rowIndexModel.row()) +
                             QByteArray(",\"modelPath\":") + Json(modelPath) +
                             QByteArray(",\"cells\":[");
      if(!WriteBytes(device, rowPrefix, error))
        return false;

      for(int colIndex = 0; colIndex < selection.columns.size(); colIndex++)
      {
        if(colIndex > 0 && !WriteBytes(device, QByteArray(","), error))
          return false;

        int column = selection.columns[colIndex];
        QModelIndex cell =
            model->index(rowIndexModel.row(), column, rowIndexModel.parent());
        if(CellSelected(selection, cell))
        {
          if(!WriteBytes(device, Json(CellObject(cell)), error))
            return false;
        }
        else
        {
          if(!WriteBytes(device, QByteArray("{\"selected\":false}"), error))
            return false;
        }

        if(!advance())
        {
          if(error)
            *error = lit("Export cancelled.");
          return false;
        }
      }

      if(!WriteBytes(device, QByteArray("]}"), error))
        return false;
    }

    return WriteBytes(device, QByteArray("]}\n"), error);
  }

  const char delimiter = format == StructuredTableFormat::CSV ? ',' : '\t';
  const QByteArray newline = format == StructuredTableFormat::CSV ? QByteArray("\r\n") : QByteArray("\n");

  if(options.includeMetadata &&
     !WriteBytes(device, MetadataDelimited(metadata, delimiter, newline), error))
    return false;

  if(options.includeHeaders)
  {
    for(int colIndex = 0; colIndex < selection.columns.size(); colIndex++)
    {
      if(colIndex > 0 && !WriteBytes(device, QByteArray(1, delimiter), error))
        return false;
      QString header =
          model->headerData(selection.columns[colIndex], Qt::Horizontal, Qt::DisplayRole).toString();
      if(!WriteBytes(device, EncodeDelimitedField(header, delimiter), error))
        return false;
    }
    if(!WriteBytes(device, newline, error))
      return false;
  }

  for(const QPersistentModelIndex &rowIndexModel : selection.rows)
  {
    for(int colIndex = 0; colIndex < selection.columns.size(); colIndex++)
    {
      if(colIndex > 0 && !WriteBytes(device, QByteArray(1, delimiter), error))
        return false;

      int column = selection.columns[colIndex];
      QModelIndex cell =
          model->index(rowIndexModel.row(), column, rowIndexModel.parent());
      QString display;
      if(CellSelected(selection, cell))
        display = cell.data(Qt::DisplayRole).toString();
      if(!WriteBytes(device, EncodeDelimitedField(display, delimiter), error))
        return false;

      if(!advance())
      {
        if(error)
          *error = lit("Export cancelled.");
        return false;
      }
    }
    if(!WriteBytes(device, newline, error))
      return false;
  }

  return true;
}

QByteArray StructuredTableExport::Encode(QAbstractItemView *view, StructuredTableFormat format,
                                         const StructuredTableMetadata &metadata,
                                         const StructuredTableOptions &options, QString *error,
                                         ProgressCallback progress)
{
  QByteArray bytes;
  QBuffer buffer(&bytes);
  if(!buffer.open(QIODevice::WriteOnly))
  {
    if(error)
      *error = buffer.errorString();
    return QByteArray();
  }

  if(!Write(view, buffer, format, metadata, options, error, progress))
    return QByteArray();
  return bytes;
}

QByteArray StructuredTableExport::EncodeModel(QAbstractItemModel *model, const QVector<int> &rows,
                                              const QVector<int> &columns,
                                              StructuredTableFormat format,
                                              const StructuredTableMetadata &metadata,
                                              const StructuredTableOptions &options, QString *error,
                                              ProgressCallback progress)
{
  Selection selection;
  for(int row : rows)
    selection.rows.push_back(QPersistentModelIndex(model ? model->index(row, 0) : QModelIndex()));
  selection.columns = columns;
  selection.rectangular = true;

  QByteArray bytes;
  QBuffer buffer(&bytes);
  if(!buffer.open(QIODevice::WriteOnly))
  {
    if(error)
      *error = buffer.errorString();
    return QByteArray();
  }

  if(!WriteModel(model, selection, buffer, format, metadata, options, error, progress))
    return QByteArray();
  return bytes;
}

bool StructuredTableExport::Save(QAbstractItemView *view, StructuredTableFormat format,
                                 const QString &filename,
                                 const StructuredTableMetadata &metadata,
                                 const StructuredTableOptions &options, QString *error,
                                 ProgressCallback progress)
{
  QSaveFile file(filename);
  if(!file.open(QIODevice::WriteOnly))
  {
    if(error)
      *error = file.errorString();
    return false;
  }

  if(!Write(view, file, format, metadata, options, error, progress))
  {
    file.cancelWriting();
    return false;
  }

  if(!file.commit())
  {
    if(error)
      *error = file.errorString();
    return false;
  }
  return true;
}

void StructuredTableExport::SaveAsync(QAbstractItemView *view, StructuredTableFormat format,
                                      const QString &filename,
                                      const StructuredTableMetadata &metadata,
                                      const StructuredTableOptions &options, QObject *context,
                                      CompletionCallback completion, ProgressCallback progress)
{
  Selection selection;
  QString initialError;
  if(!BuildSelection(view, selection, &initialError))
  {
    if(completion)
      completion(false, initialError);
    return;
  }

  struct AsyncState
  {
    QPointer<QAbstractItemModel> model;
    Selection selection;
    std::unique_ptr<QSaveFile> file;
    StructuredTableFormat format = StructuredTableFormat::CSV;
    StructuredTableMetadata metadata;
    StructuredTableOptions options;
    int rowPosition = 0;
    int columnPosition = 0;
    quint64 completed = 0;
    quint64 total = 0;
    char delimiter = ',';
    QByteArray newline;
  };

  std::shared_ptr<AsyncState> state = std::make_shared<AsyncState>();
  state->model = view->model();
  state->selection = selection;
  state->file.reset(new QSaveFile(filename));
  state->format = format;
  state->metadata = metadata;
  state->options = options;
  state->total = quint64(selection.rows.size()) * quint64(selection.columns.size());
  state->delimiter = format == StructuredTableFormat::CSV ? ',' : '\t';
  state->newline = format == StructuredTableFormat::CSV ? QByteArray("\r\n") : QByteArray("\n");

  if(!state->file->open(QIODevice::WriteOnly))
  {
    if(completion)
      completion(false, state->file->errorString());
    return;
  }

  QString error;
  if(format == StructuredTableFormat::JSON)
  {
    if(!WriteBytes(*state->file, QByteArray("{\"metadata\":"), &error) ||
       !WriteBytes(*state->file, Json(MetadataObject(metadata)), &error) ||
       !WriteBytes(*state->file, QByteArray(",\"columns\":["), &error))
    {
      state->file->cancelWriting();
      if(completion)
        completion(false, error);
      return;
    }

    for(int colIndex = 0; colIndex < selection.columns.size(); colIndex++)
    {
      if(colIndex > 0 && !WriteBytes(*state->file, QByteArray(","), &error))
        break;

      int column = selection.columns[colIndex];
      QJsonObject columnObject;
      columnObject[lit("modelColumn")] = column;
      columnObject[lit("display")] =
          state->model->headerData(column, Qt::Horizontal, Qt::DisplayRole).toString();
      if(!WriteBytes(*state->file, Json(columnObject), &error))
        break;
    }

    if(error.isEmpty() && !WriteBytes(*state->file, QByteArray("],\"rows\":["), &error))
      error = state->file->errorString();
  }
  else
  {
    if(options.includeMetadata)
      WriteBytes(*state->file, MetadataDelimited(metadata, state->delimiter, state->newline),
                 &error);

    if(error.isEmpty() && options.includeHeaders)
    {
      for(int colIndex = 0; colIndex < selection.columns.size(); colIndex++)
      {
        if(colIndex > 0 &&
           !WriteBytes(*state->file, QByteArray(1, state->delimiter), &error))
          break;
        QString header = state->model
                             ->headerData(selection.columns[colIndex], Qt::Horizontal,
                                          Qt::DisplayRole)
                             .toString();
        if(!WriteBytes(*state->file, EncodeDelimitedField(header, state->delimiter), &error))
          break;
      }
      if(error.isEmpty() && !WriteBytes(*state->file, state->newline, &error))
        error = state->file->errorString();
    }
  }

  if(!error.isEmpty())
  {
    state->file->cancelWriting();
    if(completion)
      completion(false, error);
    return;
  }

  QPointer<QObject> callbackContext(context ? context : qApp);
  std::shared_ptr<std::function<void()>> step = std::make_shared<std::function<void()>>();
  *step = [state, step, callbackContext, completion, progress]() {
    auto finish = [state, completion](bool success, const QString &message) {
      if(!success)
        state->file->cancelWriting();
      if(completion)
        completion(success, message);
    };

    if(!state->model)
    {
      finish(false, lit("The source table was destroyed during export."));
      return;
    }

    QString writeError;
    quint64 chunkCells = 0;
    while(chunkCells < 4096 && state->rowPosition < state->selection.rows.size())
    {
      QModelIndex rowIndexModel = state->selection.rows[state->rowPosition];
      if(!rowIndexModel.isValid())
      {
        finish(false, lit("The source table changed during export."));
        return;
      }

      if(state->columnPosition == 0 && state->format == StructuredTableFormat::JSON)
      {
        if(state->rowPosition > 0 &&
           !WriteBytes(*state->file, QByteArray(","), &writeError))
          break;

        QJsonArray modelPath;
        for(QModelIndex path = rowIndexModel; path.isValid(); path = path.parent())
          modelPath.prepend(path.row());
        QByteArray rowPrefix = QByteArray("{\"modelRow\":") +
                               QByteArray::number(rowIndexModel.row()) +
                               QByteArray(",\"modelPath\":") + Json(modelPath) +
                               QByteArray(",\"cells\":[");
        if(!WriteBytes(*state->file, rowPrefix, &writeError))
          break;
      }

      int column = state->selection.columns[state->columnPosition];
      QModelIndex cell =
          state->model->index(rowIndexModel.row(), column, rowIndexModel.parent());

      if(state->columnPosition > 0)
      {
        QByteArray separator =
            state->format == StructuredTableFormat::JSON
                ? QByteArray(",")
                : QByteArray(1, state->delimiter);
        if(!WriteBytes(*state->file, separator, &writeError))
          break;
      }

      if(state->format == StructuredTableFormat::JSON)
      {
        QByteArray encoded =
            CellSelected(state->selection, cell)
                ? Json(CellObject(cell))
                : QByteArray("{\"selected\":false}");
        if(!WriteBytes(*state->file, encoded, &writeError))
          break;
      }
      else
      {
        QString display;
        if(CellSelected(state->selection, cell))
          display = cell.data(Qt::DisplayRole).toString();
        if(!WriteBytes(*state->file, EncodeDelimitedField(display, state->delimiter), &writeError))
          break;
      }

      state->columnPosition++;
      state->completed++;
      chunkCells++;

      if(state->columnPosition == state->selection.columns.size())
      {
        QByteArray rowEnd =
            state->format == StructuredTableFormat::JSON ? QByteArray("]}") : state->newline;
        if(!WriteBytes(*state->file, rowEnd, &writeError))
          break;
        state->columnPosition = 0;
        state->rowPosition++;
      }
    }

    if(!writeError.isEmpty())
    {
      finish(false, writeError);
      return;
    }

    if(progress && !progress(state->completed, state->total))
    {
      finish(false, lit("Export cancelled."));
      return;
    }

    if(state->rowPosition == state->selection.rows.size())
    {
      if(state->format == StructuredTableFormat::JSON &&
         !WriteBytes(*state->file, QByteArray("]}\n"), &writeError))
      {
        finish(false, writeError);
        return;
      }

      if(!state->file->commit())
      {
        finish(false, state->file->errorString());
        return;
      }

      finish(true, QString());
      return;
    }

    if(callbackContext)
      QTimer::singleShot(0, callbackContext, [step]() { (*step)(); });
  };

  if(callbackContext)
    QTimer::singleShot(0, callbackContext, [step]() { (*step)(); });
  else
  {
    state->file->cancelWriting();
    if(completion)
      completion(false, lit("No event-loop context is available for asynchronous export."));
  }
}

bool StructuredTableExport::SaveModel(QAbstractItemModel *model, const QVector<int> &rows,
                                      const QVector<int> &columns, StructuredTableFormat format,
                                      const QString &filename,
                                      const StructuredTableMetadata &metadata,
                                      const StructuredTableOptions &options, QString *error,
                                      ProgressCallback progress)
{
  Selection selection;
  for(int row : rows)
    selection.rows.push_back(QPersistentModelIndex(model ? model->index(row, 0) : QModelIndex()));
  selection.columns = columns;
  selection.rectangular = true;

  QSaveFile file(filename);
  if(!file.open(QIODevice::WriteOnly))
  {
    if(error)
      *error = file.errorString();
    return false;
  }

  if(!WriteModel(model, selection, file, format, metadata, options, error, progress))
  {
    file.cancelWriting();
    return false;
  }

  if(!file.commit())
  {
    if(error)
      *error = file.errorString();
    return false;
  }
  return true;
}

bool StructuredTableExport::CopyTSV(QAbstractItemView *view,
                                    const StructuredTableMetadata &metadata, bool includeHeaders,
                                    QString *error)
{
  StructuredTableOptions options;
  options.includeHeaders = includeHeaders;
  options.includeMetadata = false;
  QByteArray bytes = Encode(view, StructuredTableFormat::TSV, metadata, options, error);
  if(bytes.isEmpty())
    return false;

  QClipboard *clipboard = QApplication::clipboard();
  if(clipboard == NULL)
  {
    if(error)
      *error = lit("No clipboard is available.");
    return false;
  }

  QString text = QString::fromUtf8(bytes);
  clipboard->setText(text);
  if(clipboard->text() != text)
  {
    if(error)
      *error = lit("The clipboard did not retain the exported table.");
    return false;
  }
  return true;
}

#if ENABLE_UNIT_TESTS

#include <QEventLoop>
#include <QFileInfo>
#include <QSortFilterProxyModel>
#include <QStandardItemModel>
#include <QTemporaryDir>
#include "3rdparty/catch/catch.hpp"

TEST_CASE("Structured table export quotes and preserves JSON scalar types", "[table-export]")
{
  QStandardItemModel model(2, 4);
  model.setHorizontalHeaderLabels({lit("comma,header"), lit("quote\"header"), lit("unicode"),
                                   lit("integer")});
  model.setData(model.index(0, 0), lit("a,b"));
  model.setData(model.index(0, 1), lit("quote\"value"));
  model.setData(model.index(0, 2), lit("line1\n行二"));
  model.setData(model.index(0, 3), QVariant::fromValue<qulonglong>(18446744073709551615ULL));
  model.setData(model.index(1, 0), QString());

  QVector<int> rows = {0, 1};
  QVector<int> columns = {0, 1, 2, 3};

  StructuredTableMetadata metadata;
  metadata.captureSHA256 = lit("ABC");
  metadata.eventId = 42;
  metadata.api = lit("D3D12");
  metadata.generatedAt = lit("2026-07-26T00:00:00Z");

  StructuredTableOptions options;
  options.includeMetadata = true;
  QString error;
  QByteArray csv =
      StructuredTableExport::EncodeModel(&model, rows, columns, StructuredTableFormat::CSV,
                                         metadata, options, &error);
  REQUIRE(error.isEmpty());
  REQUIRE(csv.contains("\"comma,header\""));
  REQUIRE(csv.contains("\"quote\"\"header\""));
  REQUIRE(csv.contains("\"line1\n"));
  REQUIRE(csv.contains("\r\n"));

  QByteArray json =
      StructuredTableExport::EncodeModel(&model, rows, columns, StructuredTableFormat::JSON,
                                         metadata, options, &error);
  REQUIRE(error.isEmpty());
  QJsonParseError parseError;
  QJsonDocument document = QJsonDocument::fromJson(json, &parseError);
  REQUIRE(bool(parseError.error == QJsonParseError::NoError));
  REQUIRE(document.object()[lit("metadata")].toObject()[lit("eventId")].toInt() == 42);
  QJsonObject integerCell =
      document.object()[lit("rows")].toArray()[0].toObject()[lit("cells")].toArray()[3].toObject();
  REQUIRE(bool(integerCell[lit("rawType")].toString() == lit("uint64-string")));
  REQUIRE(bool(integerCell[lit("raw")].toString() == lit("18446744073709551615")));
}

class TypedTableModel : public QAbstractTableModel
{
public:
  int rowCount(const QModelIndex & = QModelIndex()) const override { return 1; }
  int columnCount(const QModelIndex & = QModelIndex()) const override { return 8; }
  QVariant headerData(int section, Qt::Orientation orientation, int role) const override
  {
    if(orientation == Qt::Horizontal && role == Qt::DisplayRole)
      return QString::fromLatin1("c%1").arg(section);
    return QVariant();
  }
  QVariant data(const QModelIndex &index, int role) const override
  {
    if(index.row() != 0)
      return QVariant();

    if(role == Qt::DisplayRole)
    {
      if(index.column() == 5)
        return lit("0.5000 UNORM");
      if(index.column() == 6)
        return lit("ResourceId::0");
      if(index.column() == 7)
        return QString();
    }

    if(role != Qt::DisplayRole && role != Qt::EditRole)
      return QVariant();

    switch(index.column())
    {
      case 0: return QVariant::fromValue<int>(-2147483647);
      case 1: return QVariant::fromValue<uint>(4294967295U);
      case 2: return QVariant::fromValue<qlonglong>(-9223372036854775807LL);
      case 3: return QVariant::fromValue<float>(0.25F);
      case 4: return QVariant::fromValue<double>(1.0 / 3.0);
      case 5: return QVariant::fromValue<double>(0.5);
      case 6: return QVariant::fromValue(ResourceId());
      default: return QVariant();
    }
  }
};

TEST_CASE("Structured table export preserves numeric and resource identity types", "[table-export]")
{
  TypedTableModel model;
  QVector<int> rows = {0};
  QVector<int> columns = {0, 1, 2, 3, 4, 5, 6, 7};
  StructuredTableMetadata metadata;
  StructuredTableOptions options;
  QString error;

  QByteArray encoded =
      StructuredTableExport::EncodeModel(&model, rows, columns, StructuredTableFormat::JSON,
                                         metadata, options, &error);
  REQUIRE(error.isEmpty());

  QJsonDocument document = QJsonDocument::fromJson(encoded);
  QJsonArray cells =
      document.object()[lit("rows")].toArray()[0].toObject()[lit("cells")].toArray();
  REQUIRE(bool(cells[0].toObject()[lit("rawType")].toString() == lit("int32")));
  REQUIRE(bool(cells[1].toObject()[lit("rawType")].toString() == lit("uint32")));
  REQUIRE(bool(cells[2].toObject()[lit("rawType")].toString() == lit("int64-string")));
  REQUIRE(bool(cells[3].toObject()[lit("rawType")].toString() == lit("float32")));
  REQUIRE(bool(cells[4].toObject()[lit("rawType")].toString() == lit("float64")));
  REQUIRE(bool(cells[5].toObject()[lit("display")].toString() == lit("0.5000 UNORM")));
  REQUIRE(bool(cells[6].toObject()[lit("rawType")].toString() == lit("ResourceId")));
  REQUIRE(cells[7].toObject()[lit("raw")].isNull());
}

TEST_CASE("Structured table export keeps proxy order and reports I/O failures", "[table-export]")
{
  QStandardItemModel source(3, 2);
  source.setHorizontalHeaderLabels({lit("name"), lit("value")});
  source.setData(source.index(0, 0), lit("beta"));
  source.setData(source.index(0, 1), 2);
  source.setData(source.index(1, 0), lit("alpha"));
  source.setData(source.index(1, 1), 1);
  source.setData(source.index(2, 0), lit("gamma"));
  source.setData(source.index(2, 1), 3);

  QSortFilterProxyModel proxy;
  proxy.setSourceModel(&source);
  proxy.sort(0, Qt::AscendingOrder);

  QVector<int> rows = {0, 1, 2};
  QVector<int> columns = {1, 0};
  StructuredTableMetadata metadata;
  StructuredTableOptions options;
  options.includeMetadata = false;
  QString error;
  QByteArray tsv =
      StructuredTableExport::EncodeModel(&proxy, rows, columns, StructuredTableFormat::TSV,
                                         metadata, options, &error);
  REQUIRE(error.isEmpty());
  REQUIRE(tsv.startsWith("value\tname\n1\talpha\n2\tbeta\n3\tgamma\n"));

  QTemporaryDir directory;
  REQUIRE(directory.isValid());
  QString missingParent = directory.filePath(lit("missing/output.csv"));
  REQUIRE_FALSE(StructuredTableExport::SaveModel(
      &proxy, rows, columns, StructuredTableFormat::CSV, missingParent, metadata, options, &error));
  REQUIRE_FALSE(error.isEmpty());

  error.clear();
  REQUIRE_FALSE(StructuredTableExport::CopyTSV(NULL, metadata, true, &error));
  REQUIRE_FALSE(error.isEmpty());
}

class LargeTableModel : public QAbstractTableModel
{
public:
  LargeTableModel(int rows = 1001, int columns = 1000) : m_Rows(rows), m_Columns(columns) {}
  int rowCount(const QModelIndex & = QModelIndex()) const override { return m_Rows; }
  int columnCount(const QModelIndex & = QModelIndex()) const override { return m_Columns; }
  QVariant data(const QModelIndex &index, int role) const override
  {
    if(role == Qt::DisplayRole || role == Qt::EditRole)
      return index.row() * m_Columns + index.column();
    return QVariant();
  }

private:
  int m_Rows;
  int m_Columns;
};

TEST_CASE("Structured table export streams more than one million cells", "[table-export][large]")
{
  LargeTableModel model;
  QVector<int> rows;
  QVector<int> columns;
  rows.reserve(model.rowCount());
  columns.reserve(model.columnCount());
  for(int row = 0; row < model.rowCount(); row++)
    rows.push_back(row);
  for(int column = 0; column < model.columnCount(); column++)
    columns.push_back(column);

  QTemporaryDir directory;
  REQUIRE(directory.isValid());

  StructuredTableMetadata metadata;
  StructuredTableOptions options;
  options.includeMetadata = false;
  QString error;
  quint64 lastCompleted = 0;
  bool saved = StructuredTableExport::SaveModel(
      &model, rows, columns, StructuredTableFormat::CSV, directory.filePath(lit("large.csv")),
      metadata, options, &error, [&lastCompleted](quint64 completed, quint64) {
        lastCompleted = completed;
        return true;
      });
  REQUIRE(saved);
  REQUIRE(error.isEmpty());
  REQUIRE(lastCompleted == 1001000ULL);
  REQUIRE(QFileInfo(directory.filePath(lit("large.csv"))).size() > 1000000);

  error.clear();
  QString cancelledPath = directory.filePath(lit("cancelled.csv"));
  bool cancelled = StructuredTableExport::SaveModel(
      &model, rows, columns, StructuredTableFormat::CSV, cancelledPath, metadata, options, &error,
      [](quint64 completed, quint64) { return completed < 4096; });
  REQUIRE_FALSE(cancelled);
  REQUIRE_FALSE(error.isEmpty());
  REQUIRE_FALSE(QFileInfo::exists(cancelledPath));
}

TEST_CASE("Structured table export yields between asynchronous chunks", "[table-export][async]")
{
  int argc = 1;
  char applicationName[] = "structured-table-export-test";
  char *argv[] = {applicationName, NULL};
  QApplication application(argc, argv);

  LargeTableModel model(100, 100);
  QTableView view;
  view.setModel(&model);
  view.selectAll();

  QTemporaryDir directory;
  REQUIRE(directory.isValid());
  QString outputPath = directory.filePath(lit("async.json"));
  StructuredTableMetadata metadata;
  StructuredTableOptions options;
  QString completionError;
  bool completed = false;
  bool succeeded = false;
  quint64 progressCalls = 0;
  QEventLoop loop;

  StructuredTableExport::SaveAsync(
      &view, StructuredTableFormat::JSON, outputPath, metadata, options, &loop,
      [&](bool success, const QString &message) {
        completed = true;
        succeeded = success;
        completionError = message;
        loop.quit();
      },
      [&](quint64, quint64) {
        progressCalls++;
        return true;
      });

  REQUIRE_FALSE(completed);
  loop.exec();
  REQUIRE(completed);
  REQUIRE(succeeded);
  REQUIRE(completionError.isEmpty());
  REQUIRE(progressCalls > 1);
  REQUIRE(QFileInfo(outputPath).size() > 10000);

  QString cancelledPath = directory.filePath(lit("async-cancelled.csv"));
  completed = false;
  succeeded = true;
  completionError.clear();
  StructuredTableExport::SaveAsync(
      &view, StructuredTableFormat::CSV, cancelledPath, metadata, options, &loop,
      [&](bool success, const QString &message) {
        completed = true;
        succeeded = success;
        completionError = message;
        loop.quit();
      },
      [](quint64, quint64) { return false; });
  REQUIRE_FALSE(completed);
  loop.exec();
  REQUIRE(completed);
  REQUIRE_FALSE(succeeded);
  REQUIRE_FALSE(completionError.isEmpty());
  REQUIRE_FALSE(QFileInfo::exists(cancelledPath));
}

#endif    // ENABLE_UNIT_TESTS
