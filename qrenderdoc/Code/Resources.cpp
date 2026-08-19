/******************************************************************************
 * The MIT License (MIT)
 *
 * Copyright (c) 2017-2026 Baldur Karlsson
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

#include "Resources.h"
#include <QApplication>
#include <QDebug>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QHash>
#include <QImage>
#include <QIconEngine>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPainter>
#include <QSvgRenderer>
#include "QRDUtils.h"

Resources::ResourceSet *Resources::resources = NULL;

namespace
{
QHash<quint64, QString> modernPathByLegacyHash;
QHash<quint64, QIcon> modernisedIconCache;
QHash<QString, QString> lucideNameByLegacyStem;
QHash<QString, QIcon> scalableIconCache;
QHash<int, QIcon> panelIconCache;

quint64 IconPixelHash(const QPixmap &source)
{
  QImage image = source.toImage().convertToFormat(QImage::Format_ARGB32);
  if(image.size() != QSize(16, 16))
    image = image.scaled(QSize(16, 16), Qt::IgnoreAspectRatio, Qt::SmoothTransformation);

  quint64 hash = Q_UINT64_C(1469598103934665603);
  for(int y = 0; y < image.height(); y++)
  {
    const uchar *line = image.constScanLine(y);
    const int bytes = image.width() * 4;
    for(int i = 0; i < bytes; i++)
    {
      hash ^= quint64(line[i]);
      hash *= Q_UINT64_C(1099511628211);
    }
  }

  return hash;
}

QString LucidePath(const QString &name)
{
  return lit(":/modern/lucide/") + name + lit(".svg");
}

class SharpSvgIconEngine : public QIconEngine
{
public:
  explicit SharpSvgIconEngine(const QString &filename)
      : m_Monochrome(filename.startsWith(lit(":/modern/lucide/")))
  {
    QFile file(filename);
    if(file.open(QIODevice::ReadOnly))
      m_Svg = file.readAll();
  }

  SharpSvgIconEngine(const SharpSvgIconEngine &other)
      : QIconEngine(other), m_Svg(other.m_Svg), m_Monochrome(other.m_Monochrome)
  {
  }

  QIconEngine *clone() const override { return new SharpSvgIconEngine(*this); }
  QString key() const override { return lit("RDSharpSvgIconEngine"); }

  QSize actualSize(const QSize &size, QIcon::Mode, QIcon::State) override { return size; }

  QPixmap pixmap(const QSize &size, QIcon::Mode mode, QIcon::State state) override
  {
    return render(size, mode, state, 1.0);
  }

  void paint(QPainter *painter, const QRect &rect, QIcon::Mode mode, QIcon::State state) override
  {
    const qreal dpr = qMax<qreal>(1.0, painter->device()->devicePixelRatioF());
    const QSize physicalSize(qMax(1, qRound(rect.width() * dpr)),
                             qMax(1, qRound(rect.height() * dpr)));
    const QPixmap icon = render(physicalSize, mode, state, dpr);
    if(!icon.isNull())
      painter->drawPixmap(rect.topLeft(), icon);
  }

  void virtual_hook(int id, void *data) override
  {
    if(id == QIconEngine::ScaledPixmapHook)
    {
      ScaledPixmapArgument *argument = static_cast<ScaledPixmapArgument *>(data);

      // In Qt 5.9 this hook receives an already-scaled physical size. The stock SVG icon engine
      // instead returns the SVG's intrinsic 24x24 canvas for an 18 DIP request, even on a 2x
      // screen, so Qt stretches 24 pixels to 36 and softens every edge. Render this exact physical
      // size and tag it with the requested DPR to keep the vector path native to the monitor.
      argument->pixmap =
          render(argument->size, argument->mode, argument->state, argument->scale);
      return;
    }

    QIconEngine::virtual_hook(id, data);
  }

private:
  QPixmap render(const QSize &physicalSize, QIcon::Mode mode, QIcon::State state,
                 qreal devicePixelRatio)
  {
    if(m_Svg.isEmpty() || !physicalSize.isValid())
      return QPixmap();

    const qreal dpr = qMax<qreal>(1.0, devicePixelRatio);
    const QString cacheKey = QString::number(physicalSize.width()) + lit("x") +
                             QString::number(physicalSize.height()) + lit(":") +
                             QString::number(int(mode)) + lit(":") + QString::number(int(state)) +
                             lit(":") + QString::number(dpr, 'f', 3);
    if(m_PixmapCache.contains(cacheKey))
      return m_PixmapCache.value(cacheKey);

    QSvgRenderer renderer(m_Svg);
    if(!renderer.isValid())
      return QPixmap();

    QPixmap icon(physicalSize);
    icon.fill(Qt::transparent);
    QPainter painter(&icon);
    painter.setRenderHint(QPainter::Antialiasing, true);
    renderer.render(&painter, QRectF(QPointF(0.0, 0.0), QSizeF(physicalSize)));

    if(m_Monochrome && (mode != QIcon::Normal || state == QIcon::On))
    {
      QColor colour(lit("#27313B"));
      if(mode == QIcon::Disabled)
        colour = QColor(lit("#7E8993"));
      else if(state == QIcon::On || mode == QIcon::Selected)
        colour = QColor(lit("#16845A"));
      else if(mode == QIcon::Active)
        colour = QColor(lit("#236FA1"));

      // Recolour the vector coverage directly. This avoids Qt's generated disabled pixmap effect,
      // which operates on the undersized raster and visibly expands its grey fringe.
      painter.setCompositionMode(QPainter::CompositionMode_SourceIn);
      painter.fillRect(icon.rect(), colour);
    }
    else if(!m_Monochrome && mode == QIcon::Disabled)
    {
      // Preserve coloured artwork while lowering its opacity without a blur or resampling pass.
      painter.setCompositionMode(QPainter::CompositionMode_DestinationIn);
      painter.fillRect(icon.rect(), QColor(0, 0, 0, 145));
    }

    painter.end();
    icon.setDevicePixelRatio(dpr);
    m_PixmapCache.insert(cacheKey, icon);
    return icon;
  }

  QByteArray m_Svg;
  bool m_Monochrome = false;
  QHash<QString, QPixmap> m_PixmapCache;
};

QIcon ScalableIcon(const QString &filename)
{
  if(!scalableIconCache.contains(filename))
    scalableIconCache.insert(filename, QIcon(new SharpSvgIconEngine(filename)));
  return scalableIconCache.value(filename);
}

QPixmap ScalablePixmap(const QString &filename, int logicalSize, qreal devicePixelRatio)
{
  const qreal dpr = qMax<qreal>(1.0, devicePixelRatio);
  const int physicalSize = qMax(1, qRound(logicalSize * dpr));
  QPixmap pixmap(physicalSize, physicalSize);
  pixmap.fill(Qt::transparent);

  QSvgRenderer renderer(filename);
  if(renderer.isValid())
  {
    QPainter painter(&pixmap);
    painter.setRenderHint(QPainter::Antialiasing, true);
    renderer.render(&painter, QRectF(0.0, 0.0, physicalSize, physicalSize));
  }

  pixmap.setDevicePixelRatio(dpr);
  return pixmap;
}

void LoadLucideManifest()
{
  lucideNameByLegacyStem.clear();
  QFile manifest(lit(":/modern/lucide/manifest.json"));
  if(!manifest.open(QIODevice::ReadOnly))
  {
    qWarning() << "Couldn't open Lucide icon manifest";
    return;
  }

  const QJsonObject legacy = QJsonDocument::fromJson(manifest.readAll()).object().value(lit("legacy")).toObject();
  for(auto it = legacy.begin(); it != legacy.end(); ++it)
    if(it.value().isString())
      lucideNameByLegacyStem.insert(it.key(), it.value().toString());
}

QString ModernPathForLegacy(const QString &legacyFilename)
{
  QString stem = QFileInfo(legacyFilename).completeBaseName();
  if(stem.endsWith(lit("@2x")))
    stem.chop(3);

  const QString lucideName = lucideNameByLegacyStem.value(stem);
  if(!lucideName.isEmpty())
  {
    const QString path = LucidePath(lucideName);
    if(QFile::exists(path))
      return path;
  }

  QString fallback = legacyFilename;
  fallback.replace(lit(":/"), lit(":/modern/"));
  fallback.replace(lit(".png"), lit(".svg"));
  return QFile::exists(fallback) ? fallback : QString();
}

QIcon ComposePanelIcon(const QIcon &base, const QIcon &badge = QIcon())
{
  QIcon result;
  const QList<int> sizes = {16, 20, 24, 32, 48, 64};
  for(int size : sizes)
  {
    QPixmap canvas(size, size);
    canvas.fill(Qt::transparent);
    QPainter painter(&canvas);
    painter.setRenderHint(QPainter::Antialiasing, true);
    painter.drawPixmap(0, 0, base.pixmap(QSize(size, size)));
    if(!badge.isNull())
    {
      const int badgeSize = qMax(8, qRound(size * 0.5));
      const QRect badgeRect(size - badgeSize, size - badgeSize, badgeSize, badgeSize);
      painter.setCompositionMode(QPainter::CompositionMode_Clear);
      painter.fillRect(badgeRect.adjusted(-1, -1, 1, 1), Qt::black);
      painter.setCompositionMode(QPainter::CompositionMode_SourceOver);
      painter.drawPixmap(badgeRect, badge.pixmap(QSize(badgeSize, badgeSize)));
    }
    result.addPixmap(canvas);
  }
  return result;
}

QIcon CreatePanelIcon(PanelIcon panel)
{
  if(qApp->property("RDModernLight").toBool())
  {
    switch(panel)
    {
      case PanelIcon::EventBrowser: return Icons::library("list-tree");
      case PanelIcon::APIInspector: return Icons::library("scan-eye");
      case PanelIcon::Annotation: return Icons::library("message-square-text");
      case PanelIcon::Texture: return Icons::library("grid-3x3");
      case PanelIcon::Mesh: return Icons::library("boxes");
      case PanelIcon::Pipeline: return Icons::library("workflow");
      case PanelIcon::Capture: return Icons::library("camera");
      case PanelIcon::DebugMessages: return Icons::library("bug");
      case PanelIcon::DiagnosticLog: return Icons::library("file-text");
      case PanelIcon::Comments: return Icons::library("message-square-text");
      case PanelIcon::PerformanceCounters: return Icons::library("gauge");
      case PanelIcon::Statistics: return Icons::library("chart-line");
      case PanelIcon::Timeline: return Icons::library("chart-no-axes-gantt");
      case PanelIcon::Python: return Icons::library("square-terminal");
      case PanelIcon::ResourceInspector: return Icons::library("database");
      case PanelIcon::Shader: return Icons::library("code-xml");
      case PanelIcon::Buffer: return Icons::library("rows-3");
      case PanelIcon::PixelHistory: return Icons::library("rotate-ccw");
      case PanelIcon::Descriptors: return Icons::library("list");
      case PanelIcon::ShaderMessages: return Icons::library("message-square-warning");
      case PanelIcon::LiveCapture: return Icons::library("radio-tower");
      case PanelIcon::TextureList: return Icons::library("images");
      case PanelIcon::TextureInputs: return Icons::library("log-in");
      case PanelIcon::TextureOutputs: return Icons::library("log-out");
      case PanelIcon::PixelContext: return Icons::library("scan-eye");
      case PanelIcon::ResourceList: return Icons::library("database");
      case PanelIcon::RelatedResources: return Icons::library("network");
      case PanelIcon::ResourceInitialisation: return Icons::library("database-zap");
      case PanelIcon::ResourceUsage: return Icons::library("chart-line");
      case PanelIcon::Preview: return Icons::library("eye");
      case PanelIcon::MeshInput: return Icons::library("log-in");
      case PanelIcon::MeshOutput: return Icons::library("log-out");
      case PanelIcon::SourceEditor: return Icons::library("file-code");
      case PanelIcon::ProjectExplorer: return Icons::library("folder-tree");
      case PanelIcon::InteractiveConsole: return Icons::library("terminal");
      case PanelIcon::Output: return Icons::library("square-arrow-out-up-right");
      case PanelIcon::Help: return Icons::library("circle-question-mark");
      case PanelIcon::Find: return Icons::library("search");
      case PanelIcon::FindResults: return Icons::library("list-filter");
      case PanelIcon::Disassembly: return Icons::library("binary");
      case PanelIcon::Errors: return Icons::library("circle-alert");
      case PanelIcon::Compilation: return Icons::library("hammer");
      case PanelIcon::Watch: return Icons::library("eye");
      case PanelIcon::Variables: return Icons::library("variable");
      case PanelIcon::ConstantsResources: return Icons::library("sigma");
      case PanelIcon::AccessedResources: return Icons::library("database");
      case PanelIcon::Callstack: return Icons::library("layers");
      case PanelIcon::InputSignature: return Icons::library("log-in");
      case PanelIcon::OutputSignature: return Icons::library("log-out");
      case PanelIcon::FileList: return Icons::library("files");
      case PanelIcon::DebugLog: return Icons::library("bug");
    }
  }

  switch(panel)
  {
    case PanelIcon::EventBrowser: return ComposePanelIcon(Icons::timeline_marker(), Icons::action());
    case PanelIcon::APIInspector: return ComposePanelIcon(Icons::page_white_code(), Icons::find());
    case PanelIcon::Annotation: return Icons::page_white_edit();
    case PanelIcon::Texture: return Icons::checkerboard();
    case PanelIcon::Mesh: return Icons::wireframe_mesh();
    case PanelIcon::Pipeline:
      return ComposePanelIcon(Icons::page_white_stack(), Icons::arrow_join());
    case PanelIcon::Capture: return ComposePanelIcon(Icons::connect(), Icons::action());
    case PanelIcon::DebugMessages: return Icons::bug();
    case PanelIcon::DiagnosticLog:
      return ComposePanelIcon(Icons::page_white_code(), Icons::information());
    case PanelIcon::Comments: return Icons::text_add();
    case PanelIcon::PerformanceCounters:
      return ComposePanelIcon(Icons::chart_curve(), Icons::time());
    case PanelIcon::Statistics: return Icons::chart_curve();
    case PanelIcon::Timeline:
      return ComposePanelIcon(Icons::timeline_marker(), Icons::time());
    case PanelIcon::Python:
      return ComposePanelIcon(Icons::page_white_code(), Icons::action());
    case PanelIcon::ResourceInspector:
      return ComposePanelIcon(Icons::page_white_database(), Icons::find());
    case PanelIcon::Shader:
      return ComposePanelIcon(Icons::page_white_code(), Icons::wand());
    case PanelIcon::Buffer: return Icons::page_white_database();
    case PanelIcon::PixelHistory:
      return ComposePanelIcon(Icons::pixel_history(), Icons::checkerboard());
    case PanelIcon::Descriptors:
      return ComposePanelIcon(Icons::page_white_stack(), Icons::information());
    case PanelIcon::ShaderMessages:
      return ComposePanelIcon(Icons::page_white_code(), Icons::text_add());
    case PanelIcon::LiveCapture: return ComposePanelIcon(Icons::connect(), Icons::time());
    case PanelIcon::TextureList:
      return ComposePanelIcon(Icons::page_white_stack(), Icons::checkerboard());
    case PanelIcon::TextureInputs:
      return ComposePanelIcon(Icons::checkerboard(), Icons::arrow_left());
    case PanelIcon::TextureOutputs:
      return ComposePanelIcon(Icons::checkerboard(), Icons::arrow_right());
    case PanelIcon::PixelContext:
      return ComposePanelIcon(Icons::checkerboard(), Icons::zoom());
    case PanelIcon::ResourceList: return Icons::page_white_database();
    case PanelIcon::RelatedResources:
      return ComposePanelIcon(Icons::page_white_database(), Icons::link());
    case PanelIcon::ResourceInitialisation:
      return ComposePanelIcon(Icons::page_white_database(), Icons::cog());
    case PanelIcon::ResourceUsage:
      return ComposePanelIcon(Icons::page_white_database(), Icons::timeline_marker());
    case PanelIcon::Preview:
      return ComposePanelIcon(Icons::wireframe_mesh(), Icons::zoom());
    case PanelIcon::MeshInput:
      return ComposePanelIcon(Icons::wireframe_mesh(), Icons::arrow_left());
    case PanelIcon::MeshOutput:
      return ComposePanelIcon(Icons::wireframe_mesh(), Icons::arrow_right());
    case PanelIcon::SourceEditor: return Icons::page_white_code();
    case PanelIcon::ProjectExplorer:
      return ComposePanelIcon(Icons::folder_page_white(), Icons::page_white_code());
    case PanelIcon::InteractiveConsole:
      return ComposePanelIcon(Icons::page_white_code(), Icons::action());
    case PanelIcon::Output: return Icons::page_go();
    case PanelIcon::Help: return Icons::help();
    case PanelIcon::Find: return Icons::find();
    case PanelIcon::FindResults:
      return ComposePanelIcon(Icons::page_white_stack(), Icons::find());
    case PanelIcon::Disassembly:
      return ComposePanelIcon(Icons::page_white_code(), Icons::wrench());
    case PanelIcon::Errors:
      return ComposePanelIcon(Icons::page_white_code(), Icons::bug());
    case PanelIcon::Compilation:
      return ComposePanelIcon(Icons::page_white_code(), Icons::cog());
    case PanelIcon::Watch:
      return ComposePanelIcon(Icons::page_white_database(), Icons::find());
    case PanelIcon::Variables: return Icons::page_white_database();
    case PanelIcon::ConstantsResources:
      return ComposePanelIcon(Icons::page_white_database(), Icons::link());
    case PanelIcon::AccessedResources:
      return ComposePanelIcon(Icons::page_white_database(), Icons::action());
    case PanelIcon::Callstack: return Icons::page_white_stack();
    case PanelIcon::InputSignature:
      return ComposePanelIcon(Icons::page_white_code(), Icons::arrow_left());
    case PanelIcon::OutputSignature:
      return ComposePanelIcon(Icons::page_white_code(), Icons::arrow_right());
    case PanelIcon::FileList: return Icons::page_white_stack();
    case PanelIcon::DebugLog:
      return ComposePanelIcon(Icons::page_white_code(), Icons::bug());
  }

  return QIcon();
}
}

void Resources::Initialise()
{
  QList<QString> filenames;

  modernPathByLegacyHash.clear();
  modernisedIconCache.clear();
  scalableIconCache.clear();
  panelIconCache.clear();
  LoadLucideManifest();
  resources = new Resources::ResourceSet();

#undef RESOURCE_DEF
#define RESOURCE_DEF(name, filename)                                          \
  {                                                                           \
    QString fn = lit(":/" filename);                                          \
    filenames.push_back(fn);                                                  \
    resources->name##_data.pixmap = QPixmap(fn);                              \
    resources->name##_data.icon = QIcon();                                    \
    resources->name##_data.icon.addFile(fn);                                  \
    if(fn.contains(lit(".png")))                                              \
    {                                                                         \
      QString highDPIFn = fn;                                                 \
      highDPIFn.replace(lit(".png"), lit("@2x.png"));                         \
      if(QFile::exists(highDPIFn))                                            \
      {                                                                       \
        resources->name##_2x_data.pixmap = QPixmap(highDPIFn);                \
      }                                                                       \
      else                                                                    \
      {                                                                       \
        qWarning() << "Missing high-DPI @2x for " filename;                   \
        resources->name##_2x_data.pixmap = resources->name##_data.pixmap;     \
      }                                                                       \
                                                                              \
      const QString modernFn = ModernPathForLegacy(fn);                       \
      if(!modernFn.isEmpty())                                                 \
      {                                                                       \
        modernPathByLegacyHash.insert(IconPixelHash(resources->name##_data.pixmap), modernFn); \
        modernPathByLegacyHash.insert(IconPixelHash(resources->name##_2x_data.pixmap), modernFn); \
        modernPathByLegacyHash.insert(                                        \
            IconPixelHash(resources->name##_data.icon.pixmap(QSize(16, 16))), modernFn); \
        if(qApp->property("RDModernLight").toBool())                          \
        {                                                                     \
          resources->name##_data.icon = ScalableIcon(modernFn);               \
          resources->name##_data.pixmap = ScalablePixmap(modernFn, 16, 1.0);  \
          resources->name##_2x_data.pixmap = ScalablePixmap(modernFn, 16, 2.0); \
        }                                                                     \
      }                                                                       \
    }                                                                         \
  }

  RESOURCE_LIST();

  QDirIterator it(lit(":"));
  while(it.hasNext())
  {
    QString filename = it.next();
    if(filenames.contains(filename))
      continue;
    if(!filename.contains(lit(".png")))
      continue;
    if(filename.contains(lit("@2x.png")) || filename.contains(lit("@3x.png")) ||
       filename.contains(lit("@4x.png")))
      continue;

    qCritical() << "Resource not configured for" << filename;
  }
}

QIcon Resources::ModerniseIcon(const QIcon &icon)
{
  if(!qApp->property("RDModernLight").toBool() || icon.isNull() ||
     modernPathByLegacyHash.isEmpty())
    return icon;

  const quint64 cacheKey = icon.cacheKey();
  if(modernisedIconCache.contains(cacheKey))
    return modernisedIconCache.value(cacheKey);

  const quint64 pixelHash = IconPixelHash(icon.pixmap(QSize(16, 16), QIcon::Normal, QIcon::Off));
  const QString modernPath = modernPathByLegacyHash.value(pixelHash);
  const QIcon modern = modernPath.isEmpty() ? icon : ScalableIcon(modernPath);
  modernisedIconCache.insert(cacheKey, modern);
  return modern;
}

QPixmap Resources::ModernisePixmap(const QPixmap &pixmap, int logicalSize,
                                   qreal devicePixelRatio)
{
  if(!qApp->property("RDModernLight").toBool() || pixmap.isNull() ||
     modernPathByLegacyHash.isEmpty())
    return pixmap;

  const QString modernPath = modernPathByLegacyHash.value(IconPixelHash(pixmap));
  if(modernPath.isEmpty())
    return pixmap;

  return ScalablePixmap(modernPath, logicalSize, devicePixelRatio);
}

QIcon Resources::LibraryIcon(const QString &name)
{
  const QString path = LucidePath(name);
  return QFile::exists(path) ? ScalableIcon(path) : QIcon();
}

QPixmap Resources::LibraryPixmap(const QString &name, int logicalSize, qreal devicePixelRatio)
{
  const QString path = LucidePath(name);
  return QFile::exists(path) ? ScalablePixmap(path, logicalSize, devicePixelRatio) : QPixmap();
}

QIcon Icons::panel(PanelIcon panel)
{
  const int key = int(panel);
  if(!panelIconCache.contains(key))
    panelIconCache.insert(key, CreatePanelIcon(panel));
  return panelIconCache.value(key);
}

Resources::~Resources()
{
  delete resources;
}
