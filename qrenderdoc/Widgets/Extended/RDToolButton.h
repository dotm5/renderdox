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

#pragma once
#include <QElapsedTimer>
#include <QIcon>
#include <QToolButton>
#include <QVector>

class QTimer;

class RDToolButton : public QToolButton
{
private:
  Q_OBJECT
public:
  explicit RDToolButton(QWidget *parent = 0);
  ~RDToolButton();

  // Configures an opt-in, precomputed Morphicons transition for a checkable
  // button. Static local SVGs remain the reduced-motion/missing-frame fallback.
  void setMorphIcon(const QString &framePattern, int frameCount,
                    const QIcon &uncheckedFallback, const QIcon &checkedFallback,
                    qreal minProgress = -0.1, qreal maxProgress = 1.1);

signals:
  void mouseClicked(QMouseEvent *event);
  void doubleClicked(QMouseEvent *event);
  void mouseMoved(QMouseEvent *event);

public slots:

private slots:
  void morphIconToggled(bool checked);
  void morphIconTick();

protected:
  void mousePressEvent(QMouseEvent *event) override;
  void mouseMoveEvent(QMouseEvent *event) override;
  void mouseDoubleClickEvent(QMouseEvent *event) override;

private:
  void updateMorphIcon();
  bool morphAnimationEnabled() const;

  QVector<QIcon> m_MorphFrames;
  QIcon m_PreMorphIcon;
  QIcon m_MorphUncheckedFallback;
  QIcon m_MorphCheckedFallback;
  QTimer *m_MorphTimer = NULL;
  QElapsedTimer m_MorphElapsed;
  qreal m_MorphPosition = 0.0;
  qreal m_MorphVelocity = 0.0;
  qreal m_MorphTarget = 0.0;
  qreal m_MorphMinProgress = -0.1;
  qreal m_MorphMaxProgress = 1.1;
  bool m_MorphConfigured = false;
};
