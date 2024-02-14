def set_env(context, key, value):
    context.env[key] = value
    return True


def return_true(context):
    return True


def return_str(context):
    return "a string"


def return_context(context):
    context.from_inside = True
    return context
