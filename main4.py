from sklearn.model_selection import cross_val_score

def evaluate_model(model, X, y):
    scores = cross_val_score(model, X, y, cv=10)
    mean_score = round(scores.mean(), 3)
    std_score = round(scores.std(), 3)
    return mean_score, std_score


if __name__ == '__main__':
    from sklearn.datasets import load_iris
    from sklearn.tree import DecisionTreeClassifier

    data = load_iris()
    X, y = data.data, data.target
    model = DecisionTreeClassifier(random_state=0)
    mean, std = evaluate_model(model, X, y)
    print(f"Accuracy: {mean} +/- {std}")
