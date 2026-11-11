"""Generate stable, Latin-only slugs for Russian and English catalog names."""

from django.utils.text import slugify


CYRILLIC_TO_LATIN = str.maketrans({
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e',
    'ё': 'yo', 'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k',
    'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
    'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
    'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y',
    'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
})


def create_unique_slug(instance, name, fallback):
    """Find a free slug; the DB unique constraint remains the final safeguard."""
    base = slugify(name.lower().translate(CYRILLIC_TO_LATIN)) or fallback
    max_length = instance._meta.get_field('slug').max_length
    base = base[:max_length].rstrip('-')

    queryset = type(instance).objects.all()
    if instance.pk is not None:
        queryset = queryset.exclude(pk=instance.pk)

    slug = base
    counter = 2
    while queryset.filter(slug=slug).exists():
        suffix = f'-{counter}'
        slug = f'{base[:max_length - len(suffix)].rstrip("-")}{suffix}'
        counter += 1

    return slug
