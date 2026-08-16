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
#include <QHash>
#include <QImage>
#include "QRDUtils.h"

Resources::ResourceSet *Resources::resources = NULL;

namespace
{
QHash<quint64, QString> modernPathByLegacyHash;
QHash<quint64, QIcon> modernisedIconCache;

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

QPixmap TintModernIcon(const QPixmap &source, const QColor &neutral, bool preserveSemantic)
{
  QImage image = source.toImage().convertToFormat(QImage::Format_ARGB32);

  for(int y = 0; y < image.height(); y++)
  {
    QRgb *line = reinterpret_cast<QRgb *>(image.scanLine(y));
    for(int x = 0; x < image.width(); x++)
    {
      const int alpha = qAlpha(line[x]);
      if(alpha == 0)
        continue;

      const QColor original(qRed(line[x]), qGreen(line[x]), qBlue(line[x]));
      const bool semantic = preserveSemantic && original.saturation() > 80;
      const QColor result = semantic ? original : neutral;
      line[x] = qRgba(result.red(), result.green(), result.blue(), alpha);
    }
  }

  return QPixmap::fromImage(image);
}

QPixmap ModernPixmap(const QString &filename, int pixelSize, qreal devicePixelRatio)
{
  QIcon source(filename);
  QPixmap pixmap = source.pixmap(QSize(qRound(pixelSize * devicePixelRatio),
                                      qRound(pixelSize * devicePixelRatio)));
  pixmap = TintModernIcon(pixmap, QColor(0x66, 0x71, 0x7D), true);
  pixmap.setDevicePixelRatio(devicePixelRatio);
  return pixmap;
}

QIcon ModernIcon(const QString &filename)
{
  QIcon source(filename);
  QIcon icon;
  const QList<int> sizes = {16, 20, 24, 32, 48, 64, 96};

  for(int size : sizes)
  {
    const QPixmap original = source.pixmap(QSize(size, size));
    const QPixmap normal = TintModernIcon(original, QColor(0x66, 0x71, 0x7D), true);
    const QPixmap active = TintModernIcon(original, QColor(0x47, 0x7E, 0xAA), true);
    const QPixmap selected = TintModernIcon(original, QColor(0x20, 0xA7, 0x6B), true);
    const QPixmap disabled = TintModernIcon(original, QColor(0x87, 0x92, 0x9D), false);

    icon.addPixmap(normal, QIcon::Normal, QIcon::Off);
    icon.addPixmap(active, QIcon::Active, QIcon::Off);
    icon.addPixmap(selected, QIcon::Selected, QIcon::Off);
    icon.addPixmap(disabled, QIcon::Disabled, QIcon::Off);
    icon.addPixmap(selected, QIcon::Normal, QIcon::On);
    icon.addPixmap(selected, QIcon::Active, QIcon::On);
    icon.addPixmap(disabled, QIcon::Disabled, QIcon::On);
  }

  return icon;
}
}

void Resources::Initialise()
{
  QList<QString> filenames;

  modernPathByLegacyHash.clear();
  modernisedIconCache.clear();
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
      QString modernFn = fn;                                                \
      modernFn.replace(lit(":/"), lit(":/modern/"));                        \
      modernFn.replace(lit(".png"), lit(".svg"));                           \
      if(QFile::exists(modernFn))                                           \
      {                                                                       \
        modernPathByLegacyHash.insert(IconPixelHash(resources->name##_data.pixmap), modernFn); \
        if(qApp->property("RDModernLight").toBool())                          \
        {                                                                     \
          resources->name##_data.icon = ModernIcon(modernFn);                 \
          resources->name##_data.pixmap = ModernPixmap(modernFn, 16, 1.0);    \
          resources->name##_2x_data.pixmap = ModernPixmap(modernFn, 16, 2.0); \
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
  const QIcon modern = modernPath.isEmpty() ? icon : ModernIcon(modernPath);
  modernisedIconCache.insert(cacheKey, modern);
  return modern;
}

Resources::~Resources()
{
  delete resources;
}
