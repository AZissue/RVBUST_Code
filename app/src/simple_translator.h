#pragma once

#include <QHash>
#include <QString>
#include <QTranslator>

namespace app {

// Dependency-free English -> Chinese translator used until real .ts/.qm
// translation files are generated.
class SimpleTranslator : public QTranslator {
public:
    SimpleTranslator();
    QString translate(const char* context, const char* sourceText,
                      const char* disambiguation, int n) const override;

private:
    QHash<QString, QString> map_;
};

}  // namespace app

