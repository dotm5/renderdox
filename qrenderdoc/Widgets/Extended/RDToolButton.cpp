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

#include "RDToolButton.h"
#include <QApplication>
#include <QFile>
#include <QMouseEvent>
#include <QTimer>
#include <QtMath>

namespace
{
bool ReducedMotionRequested()
{
  if(qApp->property("RDReduceMotion").toBool())
    return true;

  const QByteArray setting = qgetenv("RENDERDOC_REDUCE_MOTION").trimmed().toLower();
  if(setting == "1" || setting == "true" || setting == "yes" || setting == "on")
    return true;

  return !QApplication::isEffectEnabled(Qt::UI_General);
}
}

RDToolButton::RDToolButton(QWidget *parent) : QToolButton(parent)
{
  QObject::connect(this, &QToolButton::toggled, this, &RDToolButton::morphIconToggled);
}

RDToolButton::~RDToolButton()
{
}

void RDToolButton::setMorphIcon(const QString &framePattern, int frameCount,
                                const QIcon &uncheckedFallback, const QIcon &checkedFallback,
                                qreal minProgress, qreal maxProgress)
{
  m_PreMorphIcon = icon();
  m_MorphUncheckedFallback = uncheckedFallback;
  m_MorphCheckedFallback = checkedFallback;
  m_MorphMinProgress = minProgress;
  m_MorphMaxProgress = maxProgress;
  m_MorphFrames.clear();

  if(frameCount > 1 && minProgress < maxProgress)
  {
    for(int i = 0; i < frameCount; i++)
    {
      const QString filename = framePattern.arg(i, 2, 10, QLatin1Char('0'));
      if(!QFile::exists(filename))
      {
        m_MorphFrames.clear();
        break;
      }

      const QIcon frame(filename);
      if(frame.isNull())
      {
        m_MorphFrames.clear();
        break;
      }
      m_MorphFrames.push_back(frame);
    }
  }

  if(!m_MorphTimer)
  {
    m_MorphTimer = new QTimer(this);
    m_MorphTimer->setInterval(16);
    m_MorphTimer->setTimerType(Qt::PreciseTimer);
    QObject::connect(m_MorphTimer, &QTimer::timeout, this, &RDToolButton::morphIconTick);
  }

  m_MorphConfigured = true;
  m_MorphPosition = m_MorphTarget = isChecked() ? 1.0 : 0.0;
  m_MorphVelocity = 0.0;
  updateMorphIcon();
}

bool RDToolButton::morphAnimationEnabled() const
{
  return qApp->property("RDModernLight").toBool() && !m_MorphFrames.isEmpty() &&
         !ReducedMotionRequested();
}

void RDToolButton::morphIconToggled(bool checked)
{
  if(!m_MorphConfigured)
    return;

  m_MorphTarget = checked ? 1.0 : 0.0;

  if(!qApp->property("RDModernLight").toBool())
  {
    m_MorphTimer->stop();
    m_MorphPosition = m_MorphTarget;
    m_MorphVelocity = 0.0;
    setIcon(m_PreMorphIcon);
    return;
  }

  if(!morphAnimationEnabled())
  {
    m_MorphTimer->stop();
    m_MorphPosition = m_MorphTarget;
    m_MorphVelocity = 0.0;
    updateMorphIcon();
    return;
  }

  m_MorphElapsed.restart();
  if(!m_MorphTimer->isActive())
    m_MorphTimer->start();
}

void RDToolButton::morphIconTick()
{
  if(!m_MorphConfigured || !morphAnimationEnabled())
  {
    m_MorphTimer->stop();
    m_MorphPosition = m_MorphTarget;
    m_MorphVelocity = 0.0;
    updateMorphIcon();
    return;
  }

  qreal dt = qMin(qreal(m_MorphElapsed.restart()) / 1000.0, 0.1);
  if(dt <= 0.0)
    dt = 1.0 / 60.0;

  // Morphicons 1.7.0 "snappy" spring: k=420, c=30, integrated with
  // semi-implicit Euler and at most sixteen 1/240-second substeps.
  const qreal idealStep = 1.0 / 240.0;
  const int steps = qBound(1, qCeil(dt / idealStep), 16);
  const qreal step = dt / qreal(steps);
  for(int i = 0; i < steps; i++)
  {
    const qreal acceleration = 420.0 * (m_MorphTarget - m_MorphPosition) -
                               30.0 * m_MorphVelocity;
    m_MorphVelocity += acceleration * step;
    m_MorphPosition += m_MorphVelocity * step;
  }

  const bool settled = qAbs(m_MorphTarget - m_MorphPosition) < 0.001 &&
                       qAbs(m_MorphVelocity) < 0.02;
  if(settled)
  {
    m_MorphPosition = m_MorphTarget;
    m_MorphVelocity = 0.0;
    m_MorphTimer->stop();
  }

  updateMorphIcon();
}

void RDToolButton::updateMorphIcon()
{
  if(!m_MorphConfigured)
    return;

  if(!qApp->property("RDModernLight").toBool())
  {
    setIcon(m_PreMorphIcon);
    return;
  }

  if(m_MorphFrames.isEmpty() || ReducedMotionRequested())
  {
    setIcon(m_MorphTarget >= 0.5 ? m_MorphCheckedFallback : m_MorphUncheckedFallback);
    return;
  }

  const qreal progress = qBound(m_MorphMinProgress, m_MorphPosition, m_MorphMaxProgress);
  const qreal normalised =
      (progress - m_MorphMinProgress) / (m_MorphMaxProgress - m_MorphMinProgress);
  const int frame = qBound(0, qRound(normalised * (m_MorphFrames.count() - 1)),
                           m_MorphFrames.count() - 1);
  setIcon(m_MorphFrames[frame]);
}

void RDToolButton::mousePressEvent(QMouseEvent *event)
{
  emit(mouseClicked(event));

  QToolButton::mousePressEvent(event);
}

void RDToolButton::mouseMoveEvent(QMouseEvent *event)
{
  emit(mouseMoved(event));

  QToolButton::mouseMoveEvent(event);
}

void RDToolButton::mouseDoubleClickEvent(QMouseEvent *event)
{
  emit(doubleClicked(event));

  QToolButton::mouseDoubleClickEvent(event);
}
